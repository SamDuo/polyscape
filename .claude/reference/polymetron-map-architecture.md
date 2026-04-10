# Implementation Plan v4: Map-First with Popup Cards + Bottom Brief Bar

## Core Principle

The map IS the product. No side panels. Property detail appears as a **popup above the marker** (like Google Maps). Intelligence lives in a **horizontal brief bar at the bottom** (always visible). Street View is a **mini viewer in the bottom-right corner** (like Google Maps pegman preview).

---

## Architecture

```
PAGE 1: Overview (/)
  4 district cards + market news + search bar

PAGE 2: Map view (/explore)
  Toolbar (top)
  Map (full screen, center)
  Popup card (floats above clicked marker)
  Street View mini (bottom-right corner)
  Brief bar (fixed bottom, horizontal)
```

POLYMETRON logo -> click returns to overview page.

---

## Page 1: Overview

```
+------------------------------------------------------+
|  POLYMETRON          [Search any address...]          |
+------------------------------------------------------+
|                                                      |
|  +------------------------+------------------------+ |
|  |  MIDTOWN SPI-16        |  OLD FOURTH WARD       | |
|  |  [satellite thumb]     |  [satellite thumb]     | |
|  |  $385/sqft  +3.2%      |  $310/sqft  +5.1%      | |
|  |  47 permits             |  23 permits             | |
|  |  1,777 vacant           |  892 vacant             | |
|  +------------------------+------------------------+ |
|  |  BUCKHEAD              |  WESTSIDE / BELTLINE   | |
|  |  [satellite thumb]     |  [satellite thumb]     | |
|  |  $420/sqft  -1.2%      |  $275/sqft  +8.3%      | |
|  |  31 permits             |  58 permits             | |
|  |  643 vacant             |  2,100 vacant           | |
|  +------------------------+------------------------+ |
|                                                      |
|  MARKET NEWS                                         |
|                                                      |
|  Bisnow 2h                                    +31%   |
|  Midtown Atlanta Sees Record Mixed-Use                |
|  Permits in Q1 2026                                  |
|                                                      |
|  AJC 5h                                              |
|  Cool Roof Ordinance Takes Effect -- What             |
|  Developers Need to Know                             |
|                                                      |
|  CoStar 1d                                    +18%   |
|  BeltLine Eastside Corridor: Rents Up 18% YoY        |
|                                                      |
|  City of Atlanta 2d                                  |
|  Planning Commission Approves SPI-16 Amendment        |
|                                                      |
|  GlobeSt 3d                                          |
|  Fulton County Assessments Lag Market by 15%          |
|                                                      |
+------------------------------------------------------+
```

Click district card -> navigates to /explore zoomed to that district.
Search bar -> type address -> navigates to /explore with popup open.

---

## Page 2: Map View

### Default state (no selection)

```
+----------------------------------------------------------+
|  [P]OLYMETRON  [Search...]   [Filters] [Layers] [3D]    |
+----------------------------------------------------------+
|                                                           |
|                        MAP                                |
|                    (full screen)                           |
|                                                           |
|        [450K sf]    [285K sf]                             |
|                  [42K sf]                                  |
|            [9K sf]        [38K sf]                         |
|                                                           |
|                                                           |
|                                                           |
+----------------------------------------------------------+
| BRIEF | SPI-16 at inflection point | [!]Amend [~]Roof [+]Belt | 1.Setbacks 2.Cool roof 3.BeltLine | [PDF] |
+----------------------------------------------------------+
```

### Marker clicked (popup + street view mini)

```
+----------------------------------------------------------+
|  [P]OLYMETRON  [Search...]   [Filters] [Layers] [3D]    |
+----------------------------------------------------------+
|                                                           |
|    +-------------------------------+                      |
|    | [Satellite photo]         [x] |                      |
|    |                               |                      |
|    | 1100 Peachtree St NE          |                      |
|    | [Vacant] SPI-16 Core . 0.68ac |                      |
|    |                               |                      |
|    | +------+------+------+------+ |                      |
|    | |625 ft| 25   |450K  | No   | |                      |
|    | |MAX HT| FAR  |BLD SF| VAR  | |                      |
|    | +------+------+------+------+ |                      |
|    |                               |                      |
|    | WHAT YOU CAN BUILD             |                      |
|    | 50-story mixed-use tower by    |                      |
|    | right on prime vacant site.    |                      |
|    | Full 625ft height available.   |                      |
|    | Est: $158M -- $203M            |                      |
|    |                               |                      |
|    | DEAL CHECKS                    |  +----------------+  |
|    | [check] No variance -- by right|  |                |  |
|    | [check] MARTA < 0.25 mi       |  | STREET VIEW    |  |
|    | [check] No flood zone          |  |                |  |
|    | [check] No demolition cost     |  | (live preview  |  |
|    | [warn] Heat: Moderate (72)     |  |  of selected   |  |
|    | [warn] Cool roof +$30-60K     |  |  address)       |  |
|    | [warn] 5 permits nearby        |  |                |  |
|    |                               |  | 1100 Peachtree |  |
|    | FACTS                          |  +----------------+  |
|    | Owner    Midtown Alliance LP   |                      |
|    | Held     2018                  |                      |
|    | Use      Vacant Land           |                      |
|    | Lot      0.68 ac               |                      |
|    | Assessed $4.2M                 |                      |
|    | Zoning   SPI-16-SA1            |                      |
|    | Heat     Moderate (72)         |                      |
|    | Overlays Midtown DRI, BeltLine |                      |
|    |                               |                      |
|    | [Save Site] [View 3D] [Report] |                      |
|    +---------------+---------------+                      |
|                    |                                      |
|               [450K sf]       [285K sf]                   |
|                                                           |
+----------------------------------------------------------+
| BRIEF | SPI-16 at inflection point | [!]Amend [~]Roof [+]Belt | 1.Setbacks 2.Cool roof 3.BeltLine | [PDF] |
+----------------------------------------------------------+
```

### 3D mode active

```
+----------------------------------------------------------+
|  [P]OLYMETRON  [Search...]   [Filters] [Layers] [3D*]   |
+----------------------------------------------------------+
|                                                           |
|              (map pitched to 55 degrees)                  |
|                                                           |
|              +-- -- -- -- --+                             |
|              |  wireframe   |                             |
|              |  envelope    |                             |
|              |              |                             |
|              | +----------+ |                             |
|              | | proposed | |                             |
|              | +----------+ |                             |
|              | | existing | |                             |
|              +--+----------+-+                            |
|                                                           |
+----------------------------------------------------------+
| BRIEF | ...                                               |
+----------------------------------------------------------+
```

### Filters dropdown

```
+----------------------------------------------------------+
|  [P]OLYMETRON  [Search...] [Filters*] [Layers] [3D]     |
+------------------------------+                           |
|  Height    [0] --------- [625]|                           |
|  FAR       [0] --------- [25] |        MAP               |
|  Lot size  [0] --------- [5ac]|                           |
|                               |                           |
|  Type                         |                           |
|  [ ] Vacant                   |                           |
|  [ ] Underbuilt               |                           |
|  [ ] Existing                 |                           |
|                               |                           |
|  Risk                         |                           |
|  [ ] Low  [ ] Med  [ ] High   |                           |
|                               |                           |
|  [x] No variance needed       |                           |
|                               |                           |
|  5 of 47 sites match          |                           |
|  [Apply] [Reset]              |                           |
+------------------------------+                           |
+----------------------------------------------------------+
| BRIEF | ...                                               |
+----------------------------------------------------------+
```

### Layers dropdown

```
+----------------------------------------------------------+
|  [P]OLYMETRON  [Search...] [Filters] [Layers*] [3D]     |
+----------------------------------------------------------+
|                                      +----------------+   |
|                MAP                   | LAYERS          |  |
|                                      |                |   |
|                                      | [x] Markers    |   |
|                                      | [ ] Heat Map   |   |
|                                      | [ ] Permits    |   |
|                                      | [ ] Transit    |   |
|                                      | [ ] Zoning     |   |
|                                      | [ ] Satellite  |   |
|                                      +----------------+   |
|                                                           |
+----------------------------------------------------------+
| BRIEF | ...                                               |
+----------------------------------------------------------+
```

### Compare mode (2+ saved sites)

When user has saved 2+ sites, compare button appears in brief bar:

```
+----------------------------------------------------------+
|  [P]OLYMETRON  [Search...]   [Filters] [Layers] [3D]    |
+----------------------------------------------------------+
|                                                           |
|        MAP (all saved parcels highlighted)                |
|                                                           |
|  +----------------------------------------------------+  |
|  | COMPARE 3 SITES                                [x] |  |
|  |                                                     |  |
|  |        1100         1075         725                |  |
|  |        Peachtree    Peachtree    Ponce              |  |
|  |                                                     |  |
|  | Ht     625 ft       625 ft       150 ft             |  |
|  | FAR    25.0         25.0         8.0                |  |
|  | Build  450K sf      285K sf      42K sf             |  |
|  | Cost   $158-203M    $100-128M    $15-19M            |  |
|  | Var?   No           No           No                 |  |
|  | Heat   Moderate     Moderate     HIGH               |  |
|  | Type   Vacant       Underbuilt   Underbuilt         |  |
|  |                                                     |  |
|  | [GENERATE COMPARISON REPORT]                        |  |
|  +----------------------------------------------------+  |
|                                                           |
+----------------------------------------------------------+
| BRIEF | ... | [Compare: 3 sites]                          |
+----------------------------------------------------------+
```

Compare panel slides up from above the brief bar as a floating glassmorphism card.

---

## Street View Mini Viewer

Bottom-right corner of map. Appears when a parcel is selected.

```
+--------------------+
|                    |
| (Google Street     |
|  View embed or     |
|  static image)     |
|                    |
| 1100 Peachtree     |
| [Expand] [Close]   |
+--------------------+
```

- Size: 280x200px default
- Click "Expand" -> grows to 480x320px
- Click "Close" -> hides
- If Street View not available for address, show "No street view available" with satellite fallback
- Uses Google Street View Static API: `https://maps.googleapis.com/maps/api/streetview?size=400x300&location={ADDRESS}&key={KEY}`
- If API key missing or fails, use Mapbox satellite static as fallback

### Street View API troubleshooting

If Street View images are not loading:
1. Check NEXT_PUBLIC_GOOGLE_MAPS_KEY is set in .env.local
2. In Google Cloud Console: APIs & Services -> Library -> search "Street View Static API" -> must be ENABLED
3. Check API key restrictions: if restricted by HTTP referrer, add `*.app.github.dev` for Codespaces
4. Test URL directly in browser: `https://maps.googleapis.com/maps/api/streetview?size=400x300&location=1100+Peachtree+St+NE+Atlanta+GA&key=YOUR_KEY`

---

## Brief Bar (fixed bottom, horizontal)

Always visible. Single row. Scrollable left-to-right on overflow.

```
+----------------------------------------------------------+
| BRIEF          | ALERTS        | ACTIONS            | CTA |
| Midtown SPI-16 | [!] Amendment | 1. Review setbacks | [PDF]|
| Inflection pt  | [~] Cool Roof | 2. Model cool roof |     |
|                | [+] BeltLine  | 3. Eval BeltLine   |     |
+----------------------------------------------------------+
```

Structure: 4 columns in a horizontal bar.

| Column | Content | Width |
|--------|---------|-------|
| Summary | District name + one-line assessment | ~200px |
| Alerts | 3 colored icons with short labels, clickable | ~250px |
| Actions | Numbered recommended actions | ~300px |
| CTA | Export PDF button + saved sites count | ~150px |

When a parcel is selected, brief bar updates to site-specific:

```
+----------------------------------------------------------+
| SITE BRIEF     | DEAL CHECKS   | NEARBY              | CTA |
| 1100 Peachtree | [check]x4     | 5 permits 0.5 mi   | [Report]|
| Moderate risk  | [warn]x3      | 1080: 42-fl tower   | 3 saved |
|                |               | 880: 28-fl resid    | [Compare]|
+----------------------------------------------------------+
```

### Brief bar behavior
- Default: area-level brief for current map view
- Parcel selected: switches to site-level brief
- Parcel deselected (click map/close popup): returns to area brief
- Click an alert in the bar -> popup appears with full alert detail
- Click an action -> highlights relevant layer/marker on map
- Scrollable horizontally on smaller screens

---

## Popup Card (floating above marker)

Positioned directly above the clicked marker with a pointer/arrow connecting to it. Like Google Maps info window but richer.

### Popup card specs
- Width: 340px
- Max height: 70vh (scrollable)
- Position: anchored above marker, adjusts if near edge of screen
- Border radius: 16px
- Shadow: large drop shadow for floating feel
- Close: [x] button top-right, or click outside, or click another marker
- Animation: scale up from marker point (100ms)

### Popup card sections (scrollable)

1. **Photo** (satellite from Mapbox, since it works)
   - Full width, 180px height
   - Tab to switch: [Satellite] (default since it works)
   
2. **Address + badges**
   - Address in Instrument Serif
   - [Vacant] or [Underbuilt] badge in green/orange
   - Subdistrict + lot size

3. **Metric bar** (4 boxes in a row)
   - Max Height, FAR, Buildable SF, Variance Needed

4. **What you can build**
   - Plain language paragraph
   - Estimated cost range

5. **Deal checks**
   - Green check items
   - Amber warning items

6. **Facts grid**
   - Owner, Held Since, Current Use, Year Built
   - Lot Size, Assessed, Zoning, Heat Risk, Overlays

7. **Action buttons**
   - [Save Site] [View 3D Envelope] [Generate Report]

---

## Toolbar

```
+----------------------------------------------------------+
|  [P] POLYMETRON   [Search any address...]   [Filters] [Layers] [3D] |
+----------------------------------------------------------+
```

| Element | Behavior |
|---------|----------|
| [P] Logo | Click -> return to overview page (/) |
| Search | Google Places Autocomplete. Select -> map flies to address, popup opens |
| Filters | Dropdown below toolbar. Sliders + toggles. Real-time marker filtering. |
| Layers | Dropdown top-right. Toggle: Markers, Heat Map, Permits, Transit, Zoning, Satellite. |
| 3D | Toggle. Map pitches to 55deg. deck.gl envelopes appear. |

---

## Map Markers

### Cluster markers (zoom < 13)
```
+------------------+
| MIDTOWN SPI-16   |
| 47 sites         |
| $385/sqft        |
+------------------+
```

### Individual markers (zoom >= 13)
```
+--------+
| 450K sf|
+---+----+
    |
```

Color by parcel type:
- Green background = vacant
- Orange background = underbuilt
- Gray background = existing / near capacity

Selected marker: border becomes thicker, brand color, slight scale up.

---

## Mobile Layout (< 768px)

```
+---------------------------+
| [P] [Search]  [Filters]   |
|     [Layers] [3D]         |
+---------------------------+
|                           |
|         MAP               |
|     (full screen)         |
|                           |
+---------------------------+
| --- drag handle ---       |
| Bottom sheet              |
| (popup card content)      |
| Snaps: peek / half / full |
+---------------------------+
| BRIEF BAR (compact)       |
+---------------------------+
```

- Popup card -> becomes bottom sheet (drag up to expand)
- Brief bar -> compact single row at very bottom
- Street View mini -> hidden on mobile (too small)
- Filters/Layers -> bottom sheet instead of dropdown

---

## Component Tree

```
App
  +-- OverviewPage (/)
  |     +-- SearchBar
  |     +-- DistrictGrid (4 cards)
  |     +-- MarketNews (news feed)
  |
  +-- MapPage (/explore)
        +-- Toolbar
        |     +-- Logo (link to /)
        |     +-- SearchBar (Google Places Autocomplete)
        |     +-- FilterButton -> FilterDropdown
        |     +-- LayersButton -> LayersDropdown
        |     +-- ThreeDButton (toggle)
        |
        +-- MapContainer (always mounted)
        |     +-- MapboxMap (react-map-gl)
        |     +-- DeckGLOverlay (3D envelopes, when 3D active)
        |     +-- ClusterMarkers (zoom < 13)
        |     +-- ParcelMarkers (zoom >= 13)
        |     +-- HeatLayer (toggle)
        |     +-- ZoningLayer (toggle)
        |     +-- PermitLayer (toggle)
        |
        +-- PopupCard (Framer Motion, anchored above marker)
        |     +-- PhotoHero (Satellite, with Street View tab if available)
        |     +-- AddressBadge
        |     +-- MetricBar (4 boxes)
        |     +-- WhatYouCanBuild
        |     +-- DealChecks
        |     +-- PropertyFacts
        |     +-- ActionButtons (Save, 3D, Report)
        |
        +-- StreetViewMini (bottom-right, when parcel selected)
        |     +-- Street View static image or embed
        |     +-- Expand/Close buttons
        |
        +-- BriefBar (fixed bottom, horizontal)
        |     +-- SummaryColumn
        |     +-- AlertsColumn
        |     +-- ActionsColumn
        |     +-- CTAColumn (PDF, Compare)
        |
        +-- ComparePanel (slides up above brief bar)
        |     +-- SiteColumns
        |     +-- MetricRows
        |     +-- GenerateButton
        |
        +-- BottomSheet (mobile only, replaces PopupCard)
```

---

## Data Flow

```
User action -> result

Click marker
  -> map.flyTo(parcel)
  -> PopupCard appears above marker (Framer Motion scale-in)
  -> StreetViewMini appears bottom-right
  -> BriefBar switches to site-level content

Close popup [x]
  -> PopupCard animates out
  -> StreetViewMini hides
  -> BriefBar returns to area-level

Type in search
  -> Google Places Autocomplete dropdown
  -> select address
  -> map.flyTo(coordinates)
  -> find/create parcel
  -> PopupCard appears

Toggle 3D
  -> map.easeTo({ pitch: 55, bearing: -25 })
  -> deck.gl envelope layers appear
  -> buildings grow from ground (animation)

Adjust filter
  -> filter parcel data
  -> update marker visibility (real-time)
  -> brief bar updates count

Toggle layer
  -> map layer visibility on/off

Click "Save Site"
  -> add to saved array
  -> brief bar shows saved count
  -> if 2+ saved, "Compare" button appears in brief bar CTA

Click "Compare"
  -> ComparePanel slides up above brief bar
  -> map.fitBounds(all saved parcels)

Click alert in brief bar
  -> popup with full alert detail appears on map

Click [P] logo
  -> navigate to overview page (/)
```

---

## Design System

### Colors

```css
--bg: #ffffff
--bg-warm: #f6f4f0
--ink: #1a1714
--muted: #7a7267
--brand: #1b3a2d
--accent: #c0532c
--green: #00c853
--amber: #ff9100
--red: #ff1744
--line: #f0f0f0
```

### Glassmorphism (popup card + brief bar + dropdowns)

```css
backdrop-filter: blur(16px) saturate(180%);
background: rgba(255, 255, 255, 0.92);
border: 1px solid rgba(255, 255, 255, 0.3);
border-radius: 16px;
box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);

/* Tailwind */
className="backdrop-blur-xl bg-white/92 border border-white/30 rounded-2xl shadow-xl"
```

### Typography

```
Instrument Serif: popup card address, brief bar title, overview headers
Manrope: everything else
```

### Icons: Lucide React

### Components: shadcn/ui + Aceternity UI

---

## Tech Stack

```
Next.js 14 (App Router, 2 routes: / and /explore)
Tailwind CSS
shadcn/ui + Aceternity UI
Lucide React
Framer Motion (popup animations, compare panel slide)
react-map-gl + deck.gl
Recharts (chart on overview page)
Google Places Autocomplete
Google Street View Static API
Mapbox Static API (satellite, always works)
```

---

## Implementation Steps

| Step | What | Time |
|------|------|------|
| 1 | Next.js + Tailwind + shadcn/ui scaffold | 30 min |
| 2 | Overview page: 4 district cards + market news | 1 hr |
| 3 | Map page: full-screen MapContainer with react-map-gl | 30 min |
| 4 | Toolbar: logo, search, filters, layers, 3D buttons | 30 min |
| 5 | Parcel markers with labels (color-coded) | 45 min |
| 6 | Cluster markers at low zoom | 30 min |
| 7 | PopupCard component (anchored above marker) | 1.5 hr |
| 8 | Popup content: photo, metrics, deal checks, facts | 1 hr |
| 9 | Click marker -> popup appears + map flies | 30 min |
| 10 | StreetViewMini (bottom-right, static image) | 30 min |
| 11 | BriefBar (fixed bottom, horizontal 4-column) | 1 hr |
| 12 | Brief bar: area-level vs site-level switching | 30 min |
| 13 | SearchBar with Google Places Autocomplete | 45 min |
| 14 | FilterDropdown with real-time marker filtering | 45 min |
| 15 | LayersDropdown with toggle switches | 30 min |
| 16 | 3D toggle + deck.gl wireframe envelopes | 1 hr |
| 17 | Save site + compare flow | 1 hr |
| 18 | ComparePanel (slides up above brief bar) | 45 min |
| 19 | Glassmorphism on popup + brief bar + dropdowns | 30 min |
| 20 | Mobile bottom sheet (replaces popup) | 1 hr |
| 21 | Framer Motion animations (popup scale, compare slide) | 30 min |
| 22 | Overview -> map transition animation | 30 min |

Total: ~15 hours. Steps 1-9 (~7 hours) give you a working map with popup cards.

---

## What This Replaces

Supersedes all previous plans:
- map-first-architecture.md (v3 - left panel)
- multipage-webapp-v2.md (v2 - Redfin split)
- multipage-webapp.md (v1 - 6 pages)

---

## SESSION_ID
- CODEX_SESSION: N/A
- GEMINI_SESSION: N/A
