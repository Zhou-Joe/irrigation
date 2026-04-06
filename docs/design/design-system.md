---
name: design-system
description: Harmonized design system for Horticulture Management System
type: project
---

# Horticulture Management System - Design System

**Aesthetic Direction:** Modern Botanical - organic elegance with data-driven precision

## Concept

A sophisticated design system that bridges natural botanical themes with modern agricultural technology. Think: vintage botanical illustration meets contemporary dashboard. Warm, grounded, yet crisp and functional.

## Typography

### Display Font
**Font:** `Playfair Display` - elegant serif with botanical character
- Use for: Zone names, section headers, modal titles
- Weight: 600 (semi-bold) for primary, 400 for secondary

### Body Font
**Font:** `DM Sans` - modern geometric sans-serif, clean but warm
- Use for: Data labels, descriptions, UI text, buttons
- Weight: 400 regular, 500 medium for emphasis

### Monospace (Data)
**Font:** `JetBrains Mono` - for timestamps, codes, coordinates
- Use sparingly for technical data display

## Color Palette

### Primary (Deep Forest)
```css
--color-primary: #1B4332;       /* Deep forest green - headers, primary actions */
--color-primary-light: #2D6A4F; /* Mid forest - hover states */
--color-primary-dark: #081C15;  /* Near-black forest - emphasis */
```

### Accent (Golden Pollen)
```css
--color-accent: #D4A574;        /* Warm golden - highlights, badges */
--color-accent-light: #E8C9A0;  /* Pale gold - subtle highlights */
--color-accent-dark: #B8956A;   /* Deep amber - active states */
```

### Surface (Earth Tones)
```css
--color-surface: #F5F0E8;       /* Warm paper/off-white - backgrounds */
--color-surface-alt: #EDE8DC;   /* Slightly darker - card backgrounds */
--color-surface-dark: #D9D0C0;  /* Subtle contrast - section dividers */
```

### Semantic (Status Colors)
```css
--color-success: #40916C;       /* Fresh green - done/completed */
--color-warning: #CC7722;       /* Ochre - working/in-progress */
--color-info: #52B788;          /* Leaf green - scheduled */
--color-error: #9B2226;         /* Terracotta red - canceled/error */
--color-delayed: #7B5544;       /* Brown - delayed status */
```

### Text
```css
--color-text-primary: #1B4332;  /* Match primary for cohesion */
--color-text-secondary: #4A6355; /* Muted forest - descriptions */
--color-text-muted: #8B9A8F;    /* Grey-green - disabled/placeholder */
--color-text-inverse: #F5F0E8;  /* Light text on dark backgrounds */
```

## Spatial System

```css
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 32px;
--space-2xl: 48px;
--space-3xl: 64px;
```

## Component Styles

### Cards
- Rounded corners: 12px
- Subtle shadow: `0 2px 8px rgba(27, 67, 50, 0.08)`
- Border: 1px solid `--color-surface-dark`
- Background: `--color-surface-alt`

### Buttons
**Primary:**
```css
background: var(--color-primary);
color: var(--color-text-inverse);
border-radius: 8px;
padding: 12px 24px;
font-family: 'DM Sans', sans-serif;
font-weight: 500;
transition: all 0.2s ease;
/* Hover: background shifts to --color-primary-light, subtle scale(1.02) */
```

**Secondary:**
```css
background: transparent;
color: var(--color-primary);
border: 2px solid var(--color-primary);
/* Hover: fill with --color-primary-light background */
```

### Zone Map Polygons
```css
/* Default zone fill */
fillColor: 'rgba(45, 106, 79, 0.25)';
strokeColor: '#2D6A4F';
strokeWidth: 2;

/* Highlighted/selected */
fillColor: 'rgba(212, 165, 74, 0.4)';
strokeColor: '#D4A574';
strokeWidth: 3;

/* Status-based colors */
--zone-done: rgba(64, 145, 108, 0.35);
--zone-working: rgba(204, 119, 34, 0.35);
--zone-scheduled: rgba(82, 183, 136, 0.25);
--zone-canceled: rgba(155, 34, 38, 0.25);
--zone-delayed: rgba(123, 85, 68, 0.35);
```

### Status Badges
```css
/* Pill-shaped with subtle gradient */
padding: 4px 12px;
border-radius: 20px;
font-size: 12px;
font-weight: 500;
font-family: 'DM Sans', sans-serif;
text-transform: uppercase;
letter-spacing: 0.5px;
```

## Motion Guidelines

### Transitions
```css
--transition-fast: 150ms ease;
--transition-base: 250ms ease;
--transition-slow: 400ms ease;
```

### Micro-interactions
- Card hover: gentle lift + shadow increase
- Button press: scale(0.98) + brief color shift
- Zone polygon: opacity pulse on hover
- Modal: fade + slide from bottom

### Page Load
- Staggered reveal for cards (50ms delay each)
- Map tiles fade in
- Header elements slide in from top

## Backgrounds & Atmosphere

### Main Background Pattern
Subtle botanical line drawing overlay at 5% opacity - suggests foliage without distraction

### Dashboard
Gradient mesh: warm cream fading to subtle green at edges
```css
background: linear-gradient(135deg, #F5F0E8 0%, #EDE8DC 50%, #E8E3D5 100%);
```

## Iconography

Use `Lucide` icons with custom color styling:
- Map: `MapPin`, `Map`, `Layers`
- Status: `CheckCircle2`, `Clock`, `AlertCircle`, `XCircle`
- Actions: `Plus`, `Upload`, `RefreshCw`, `Settings`
- Navigation: `ChevronRight`, `Menu`, `Home`

## Accessibility

- Minimum contrast ratio: 4.5:1 for text
- Focus states: 2px golden ring (`--color-accent`)
- All interactive elements: minimum 44px touch target
- Screen reader labels on all map zones

## How to Apply

1. **Internal Server Dashboard**: Apply typography, card styles, map polygon colors, status badges
2. **Mobile App**: Simplified version - focus on buttons, zone colors, status badges
3. **Cloud Relay**: Minimal - just consistent error/success messaging format

**Why:** Creates a cohesive brand identity that feels professional yet warm, suitable for agricultural/horticultural context while avoiding generic tech aesthetics.

**How to apply:** Reference this design system for all UI implementations. Each subagent should extract relevant sections for their component.