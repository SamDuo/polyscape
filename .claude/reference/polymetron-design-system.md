# Polymetron — Urban Intelligence Platform

## What This Is

Polymetron is a GeoAI platform that delivers urban intelligence for resilient cities. "The city is the market. Polymetron is the intelligence layer." Business model is consulting-as-a-service ($75K-200K/yr engagements), not SaaS.

**Positioning:** "Palantir for the physical world, starting with climate." Autonomous agents that monitor cities, detect risk patterns, and push actionable briefs to decision-makers.

**Target investors:** a16z American Dynamism (Speedrun), Menlo Ventures.

## Tech Stack (Target — Next.js in Codespaces)

- **Framework:** Next.js 14+ (App Router)
- **UI:** React + Tailwind CSS
- **Map:** react-map-gl (Mapbox GL JS wrapper)
- **3D:** deck.gl (GeoJsonLayer with wireframe for zoning envelopes)
- **Charts:** Chart.js or Recharts
- **Data:** Supabase (vector store for RAG), Atlanta ArcGIS Open Data
- **AI:** OpenAI embeddings + GPT-4o for zoning RAG chat
- **Deploy:** Vercel

## Design System

Fonts: Instrument Serif (headings), Manrope (body)

```css
--bg: #f6f4f0        /* warm cream background */
--ink: #1a1714        /* near-black text */
--muted: #7a7267      /* secondary text */
--accent: #c0532c     /* burnt orange CTA */
--brand: #1b3a2d      /* dark green (sidebar, agent panel) */
--green: #2c6b4f      /* success, active indicators */
--line: #e2ddd4       /* borders */
--surface: #fff       /* cards */
```

## Architecture: Three Pillars (from landing page)

1. **Agentic Digital Twin** — map with HVI choropleth, heat vulnerability index, cream bg
2. **Autonomous Agents** — dark panel (#1b3a2d bg), agent speaks first with alerts, accent pill buttons for follow-ups, split layout: chat left + map right
3. **Intervention Simulation** — scenario testing for tree canopy, cooling centers, development

## Key Feature: 3D Zoning Envelope

Three layers rendered on one map view per parcel:
1. **Zoning Envelope** (wireframe, cyan) — max buildable volume from zoning code via deck.gl GeoJsonLayer with `wireframe: true`
2. **Existing Building** (solid gray) — actual current height via Mapbox fill-extrusion
3. **Proposed Massing** (accent color, semi-transparent) — proposed development via Mapbox fill-extrusion

Toggle between 2D (pitch: 0) and 3D (pitch: 55, bearing: -25) views.

## Demo Data

- **Atlanta SPI-16** — 6 subdistricts (Core, Village, Garden, Transition, Georgia Tech, BeltLine Eastside)
- **12,550** building code passages indexed (RAG pipeline)
- **35,290** sales records (Fulton County Tax Assessor, 2011-2022)
- **atlanta-tracts.geojson** — census tracts with HVI data
- **5 demo parcels** with zoning heights, existing heights, proposed heights, risk scores

## Consulting Delivery Framing

The UI should feel like an **intelligence briefing**, not a SaaS dashboard:
- Nav: "Situation Brief" / "Site Report" / "Market Intelligence"
- Sidebar: Agent Status with pulse dots (Zoning Analyst: ACTIVE, Market Monitor: ACTIVE, Risk Scanner: MONITORING)
- Detail panel: Dark (#1b3a2d) with "Polymetron AI" header, agent speaks first with red alert cards
- Toolbar: "ENGAGEMENT: Midtown Atlanta SPI-16 | PROPRIETARY"
- CTAs: "Generate Client Report", "Export Intelligence Brief"

## Competitive Landscape

| Competitor | What They Do | Polymetron Differentiator |
|-----------|-------------|-------------------------|
| Deepblocks ($55/mo) | 3D massing + financial pro forma | Climate risk overlay, consulting model |
| Smart Bricks (a16z, $5M) | AI property investing | No zoning, no climate, no food security |
| Algoma | Zoning-only SaaS | No climate, no intervention sim |
| First Street ($46M) | Climate risk scores | No zoning, no food, no intervention sim |

## Data Sources

### Free / Immediate
- Atlanta ArcGIS Open Data (zoning polygons, overlays, NPU boundaries)
- Atlanta Building Permits 2019-2024 (ARC Open Data)
- Census/HUD residential permits
- RSS feeds (Bisnow ATL, AJC RE, CoStar)

### Low Cost ($95-200/mo)
- ATTOM API ($95/mo) — 158M properties, sales, permits, valuations
- Google Maps / Mapbox Satellite — Street View imagery
- Regrid API (free tier) — parcel boundaries

### Scale (post-raise)
- Mapbox Tiling Service — vector tilesets for millions of parcels
- Regrid Enterprise (~$80K/yr) — nationwide parcels
- Shovels.ai — AI-enriched permit data

## API Keys (set in .env.local)

```bash
NEXT_PUBLIC_MAPBOX_TOKEN=       # Mapbox GL JS + Static Images (satellite)
NEXT_PUBLIC_GOOGLE_MAPS_KEY=    # Google Street View Static API (building photos)
```

- Mapbox token: account username `sduong`, free 50K tile loads/mo
- Google Maps: get free key at console.cloud.google.com → APIs & Services → enable "Street View Static API". Free $200/mo credit (~28K Street View images/mo)

## Commands

```bash
# Dev
npm run dev

# Build
npm run build

# Deploy
npx vercel --prod
```

## File Structure (Target)

```
src/
  app/
    page.tsx                # Main dashboard
    layout.tsx              # Root layout with sidebar
  components/
    map/
      MapView.tsx           # react-map-gl + deck.gl overlay
      ZoningEnvelope.tsx    # 3D wireframe envelope layer
      BuildingLayers.tsx    # Existing + proposed extrusions
      MapLegend.tsx
      MapControls.tsx       # 2D/3D toggle, layer switches
    panel/
      AgentPanel.tsx        # Dark panel with intelligence brief
      AlertCard.tsx         # Red/amber/green alert cards
      ParcelDetail.tsx      # Parcel click detail with bar chart
      ZoneDetail.tsx        # Zone tabs (overview, code, feasibility, agent)
    sidebar/
      Sidebar.tsx
      AgentStatus.tsx       # Pulse dot + status indicators
      Navigation.tsx
    charts/
      RatioChart.tsx
      DeltaChart.tsx
      TierChart.tsx
    chat/
      AgentChat.tsx         # Agent-first chat with preset pills
  data/
    zones.ts                # 6 subdistrict definitions
    parcels.ts              # Demo parcel data with heights + risk
    news.ts                 # Pre-cached news headlines
    permits.ts              # Recent building permits
  lib/
    mapbox.ts               # Mapbox token + config
    zoning.ts               # Zoning envelope computation
  styles/
    globals.css             # Design system variables
```
