#!/usr/bin/env bash
# Setup CCG (Claude Code Generator) multi-model harness
# Installs codeagent-wrapper + role prompts for Codex and Gemini backends
set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
CCG_DIR="$CLAUDE_DIR/.ccg"
BIN_DIR="$CLAUDE_DIR/bin"

echo "=== Setting up CCG Multi-Model Harness ==="

# 1. Create directory structure
mkdir -p "$BIN_DIR"
mkdir -p "$CCG_DIR/prompts/codex"
mkdir -p "$CCG_DIR/prompts/gemini"

# 2. Install codeagent-wrapper via npm
if command -v npm &>/dev/null; then
  echo "Installing codeagent-wrapper..."
  npm install -g @anthropic/codeagent-wrapper 2>/dev/null || {
    echo "WARN: @anthropic/codeagent-wrapper not found on npm."
    echo "Creating a minimal wrapper script instead..."
    cat > "$BIN_DIR/codeagent-wrapper" << 'WRAPPER'
#!/usr/bin/env bash
# Minimal codeagent-wrapper: routes prompts to Codex or Gemini APIs
set -euo pipefail

BACKEND=""
GEMINI_MODEL="gemini-3-pro-preview"
SESSION_ID=""
RESUME=""
PROJECT_DIR=""
LITE_MODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2 ;;
    --gemini-model) GEMINI_MODEL="$2"; shift 2 ;;
    --lite) LITE_MODE="true"; shift ;;
    resume) RESUME="$2"; shift 2 ;;
    -) PROJECT_DIR="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# Read stdin (the prompt)
PROMPT=$(cat)

# Extract role file if specified
ROLE_FILE=$(echo "$PROMPT" | grep "^ROLE_FILE:" | head -1 | sed 's/ROLE_FILE: *//')
TASK=$(echo "$PROMPT" | sed '/^ROLE_FILE:/d')

# Load role prompt if file exists
ROLE_CONTENT=""
if [[ -n "$ROLE_FILE" && -f "$ROLE_FILE" ]]; then
  ROLE_CONTENT=$(cat "$ROLE_FILE")
fi

FULL_PROMPT="$ROLE_CONTENT

$TASK"

if [[ "$BACKEND" == "codex" ]]; then
  # Route to OpenAI Codex/GPT-4
  if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: OPENAI_API_KEY not set" >&2
    exit 1
  fi

  PAYLOAD=$(jq -n \
    --arg model "gpt-4.1" \
    --arg prompt "$FULL_PROMPT" \
    '{model: $model, messages: [{role: "user", content: $prompt}], max_tokens: 16384, temperature: 0.2}')

  RESPONSE=$(curl -s https://api.openai.com/v1/chat/completions \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

  echo "$RESPONSE" | jq -r '.choices[0].message.content // .error.message'

  # Generate session ID
  SESSION_ID="codex-$(date +%s)"
  echo ""
  echo "SESSION_ID: $SESSION_ID"

elif [[ "$BACKEND" == "gemini" ]]; then
  # Route to Google Gemini
  if [[ -z "${GEMINI_API_KEY:-}" ]]; then
    echo "ERROR: GEMINI_API_KEY not set" >&2
    exit 1
  fi

  PAYLOAD=$(jq -n \
    --arg prompt "$FULL_PROMPT" \
    '{contents: [{parts: [{text: $prompt}]}], generationConfig: {temperature: 0.2, maxOutputTokens: 16384}}')

  RESPONSE=$(curl -s "https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

  echo "$RESPONSE" | jq -r '.candidates[0].content.parts[0].text // .error.message'

  SESSION_ID="gemini-$(date +%s)"
  echo ""
  echo "SESSION_ID: $SESSION_ID"

else
  echo "ERROR: --backend must be 'codex' or 'gemini'" >&2
  exit 1
fi
WRAPPER
    chmod +x "$BIN_DIR/codeagent-wrapper"
    echo "Created minimal wrapper at $BIN_DIR/codeagent-wrapper"
  }
else
  echo "ERROR: npm not found. Install Node.js first."
  exit 1
fi

# 3. Create role prompts for Codex
cat > "$CCG_DIR/prompts/codex/analyzer.md" << 'EOF'
# Role: Backend Technical Analyzer

You are an expert backend engineer analyzing a codebase for implementation planning.

Focus on:
- Technical feasibility and architecture impact
- Performance considerations and bottlenecks
- Data flow and API design
- Error handling and edge cases
- Security implications
- Testing strategy

Provide multi-perspective analysis with pros/cons for each approach.
EOF

cat > "$CCG_DIR/prompts/codex/architect.md" << 'EOF'
# Role: Backend Architect

You are a senior backend architect designing implementation for a Python/FastAPI GeoAI application.

Focus on:
- Clean architecture with separation of concerns
- Efficient data pipelines (Parquet, H3 spatial indexing)
- API endpoint design (FastAPI, async where beneficial)
- ML model serving (XGBoost, SHAP explanations)
- Caching strategy (Redis)
- Error handling and validation

Output: Unified Diff Patch format. Do NOT modify any files directly.
EOF

cat > "$CCG_DIR/prompts/codex/reviewer.md" << 'EOF'
# Role: Backend Code Reviewer

Review the provided code changes for:
1. Security vulnerabilities (injection, auth, data exposure)
2. Performance issues (N+1 queries, memory leaks, blocking I/O)
3. Error handling completeness
4. API contract correctness
5. Data validation at boundaries
6. Type safety and edge cases

Output: Prioritized list of issues with severity, file, and rationale.
Include Unified Diff Patch for any concrete fixes.
EOF

# 4. Create role prompts for Gemini
cat > "$CCG_DIR/prompts/gemini/analyzer.md" << 'EOF'
# Role: Frontend/UX Analyzer

You are an expert frontend engineer analyzing UI/UX for a geographic visualization application.

Focus on:
- User experience and interaction design
- Visual hierarchy and information density
- Accessibility (WCAG compliance)
- Performance (rendering, animation smoothness)
- Responsive design considerations
- Map interaction patterns

Provide multi-perspective analysis with pros/cons for each approach.
EOF

cat > "$CCG_DIR/prompts/gemini/frontend.md" << 'EOF'
# Role: Frontend Developer

You are a senior frontend developer implementing a Mapbox GL JS + D3.js geographic visualization.

Focus on:
- Mapbox GL JS v3 best practices (expressions, layers, sources)
- D3.js integration (SVG overlays, data joins, transitions)
- Deck.gl layer configuration
- Smooth zoom-driven transitions between visual encodings
- DOM performance (marker pooling, visibility culling)
- CSS animations and dark theme consistency

Output: Unified Diff Patch format. Do NOT modify any files directly.
EOF

cat > "$CCG_DIR/prompts/gemini/reviewer.md" << 'EOF'
# Role: Frontend Code Reviewer

Review the provided code changes for:
1. Accessibility issues (screen readers, keyboard nav, color contrast)
2. Design consistency (color tokens, spacing, typography)
3. Animation/transition smoothness
4. DOM performance (excessive reflows, marker count)
5. Cross-browser compatibility
6. User interaction edge cases

Output: Prioritized list of issues with severity, file, and rationale.
Include Unified Diff Patch for any concrete fixes.
EOF

echo ""
echo "=== CCG Setup Complete ==="
echo "Wrapper: $BIN_DIR/codeagent-wrapper"
echo "Prompts: $CCG_DIR/prompts/"
echo ""
echo "Required env vars:"
echo "  OPENAI_API_KEY  - for Codex backend"
echo "  GEMINI_API_KEY  - for Gemini backend"
echo ""
echo "Test with:"
echo "  ~/.claude/bin/codeagent-wrapper --backend codex - \"\$PWD\" <<< 'Hello from Codex'"
echo "  ~/.claude/bin/codeagent-wrapper --backend gemini --gemini-model gemini-3-pro-preview - \"\$PWD\" <<< 'Hello from Gemini'"
