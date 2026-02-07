# AaltoHub v2 Design System

**Version**: 2.0 (Modern Refined Aesthetic)
**Last Updated**: 2026-02-06

## Design Philosophy

AaltoHub v2 uses a **clean, minimal dashboard aesthetic** that emphasizes:
- **Typography-first design**: Bold, large headings guide the user experience
- **Subtle depth**: Soft shadows and refined borders instead of harsh contrasts
- **White space**: Generous padding and spacing for readability
- **Semantic colors**: Clear visual hierarchy through deliberate color usage
- **Accessibility**: High contrast ratios and proper focus states

---

## Color Palette

### Light Mode

**Primary Colors:**
- Primary: `#0084d4` (Telegram Blue - refined)
- Accent: `#00d4ff` (Vibrant Cyan)

**Base Colors:**
- Background: `#ffffff` (Pure White)
- Foreground: `#0f1419` (Near Black)
- Card: `#f8f9fb` (Subtle Gray)

**Interactive Elements:**
- Secondary: `#e8eef5` (Light Gray-Blue)
- Muted: `#d0d7e1` (Gray)
- Muted Foreground: `#626d7d` (Medium Gray)
- Border: `#e1e8f0` (Light Border)
- Input: `#e1e8f0` (Input Field Color)
- Ring: `#0084d4` (Focus Ring - Primary)
- Destructive: `#ef4444` (Red)

**Sidebar:**
- Sidebar Background: `#f8f9fb`
- Sidebar Border: `#e1e8f0`
- Sidebar Primary: `#0084d4`
- Sidebar Accent: `#00d4ff`

### Dark Mode

**Primary Colors:**
- Primary: `#00a0e9` (Brighter Blue for contrast)
- Accent: `#00d4ff` (Same vibrant cyan)

**Base Colors:**
- Background: `#0f1419` (Deep Dark)
- Foreground: `#eceff4` (Light Off-White)
- Card: `#1a1f2e` (Dark Blue-Gray)
- Border: `#2a323f` (Subtle Dark Gray)
- Input: `#2a323f`

**Interactive Elements:**
- Secondary: `#252d3d`
- Muted: `#3a424f`
- Muted Foreground: `#9ca3af`
- Destructive: `#f87171` (Lighter Red)

---

## Typography System

### Font Families

```css
/* Display: Bold, eye-catching headings */
font-family: 'Space Grotesk', sans-serif;

/* Body: Readable, comfortable text */
font-family: 'Inter', sans-serif;

/* Monospace: Code, timestamps, technical content */
font-family: 'JetBrains Mono', monospace;
```

### Typography Scale

| Element | Size | Weight | Line Height | Letter Spacing | Usage |
|---------|------|--------|-------------|----------------|-------|
| **H1** | 40px (2.5rem) | 700 Bold | 1.25 | -0.02em | Page titles, primary headlines |
| **H2** | 30px (1.875rem) | 700 Bold | 1.25 | -0.01em | Section titles |
| **H3** | 24px (1.5rem) | 700 Bold | 1.375 | normal | Sub-section titles, card titles |
| **H4** | 20px (1.25rem) | 600 Semi | 1.375 | normal | Small headings |
| **Body** | 16px (1rem) | 400 Regular | 1.5 | normal | Main content text |
| **Body Small** | 14px (0.875rem) | 400 Regular | 1.5 | normal | Secondary text, descriptions |
| **Caption** | 12px (0.75rem) | 400 Regular | 1.5 | normal | Timestamps, small labels |

### Typography Usage Guidelines

```tsx
// Page title (always use h1)
<h1 className="text-4xl font-bold">관리자 대시보드</h1>

// Section title (use h2)
<h2 className="text-3xl font-bold">등록된 그룹</h2>

// Sub-section (use h3 or CardTitle)
<h3 className="text-2xl font-bold">그룹 설정</h3>
<CardTitle>Settings</CardTitle>  {/* Renders as text-2xl */}

// Card heading (use h4 or h3)
<h4 className="text-xl font-semibold">Options</h4>

// Body text (default, no special classes)
<p>Regular paragraph text goes here</p>

// Small descriptive text
<p className="text-sm text-muted-foreground">Secondary description</p>

// Captions, timestamps
<span className="text-xs text-muted-foreground">Updated 2 hours ago</span>
```

---

## Spacing System

Based on `1rem (16px)` base unit:

| Unit | Size | Use Case |
|------|------|----------|
| **xs** | 8px | Tight spacing |
| **sm** | 12px | Compact spacing between elements |
| **md** | 16px | Default spacing, body padding |
| **lg** | 24px | Comfortable spacing, section spacing |
| **xl** | 32px | Generous spacing, major sections |
| **2xl** | 48px | Large spacing between major blocks |

**Common Spacing Patterns:**

```tsx
// Section content padding
<div className="p-6">...</div>

// Gap between vertical items
<div className="space-y-4">...</div>

// Gap between horizontal items
<div className="flex gap-2">...</div>

// Section margins
<div className="mb-8">...</div>

// Container padding by breakpoint
<div className="px-4 sm:px-6 lg:px-8 py-6">...</div>
```

---

## Border & Shadow System

### Borders

Use **minimal, subtle borders** instead of thick dividers:

```css
/* Standard border */
border: 1px solid var(--border);

/* Used for: Card edges, input fields, section dividers */
className="border border-border"

/* Divider between sections (no added margin needed) */
className="border-b border-border"
```

**⚠️ NEVER use:**
- `border-2` (too heavy)
- `border-4`, `border-b-4` (brutalist remnants)

**Exception:** Code input fields can use `border-2 border-primary` for emphasis.

### Shadows

**Soft, layered shadows provide depth:**

```css
/* Subtle shadow (default cards) */
box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 1px 2px 0 rgba(0, 0, 0, 0.03);
className="shadow-sm shadow-black/5"

/* Elevated shadow (hover states) */
box-shadow: 0 4px 12px 0 rgba(0, 0, 0, 0.08), 0 2px 4px 0 rgba(0, 0, 0, 0.04);
className="shadow-md shadow-black/8"

/* Deep shadow (modals, dialogs) */
box-shadow: 0 10px 24px 0 rgba(0, 0, 0, 0.1);
className="shadow-xl shadow-black/10"

/* Button shadows */
className="shadow-md shadow-primary/20"

/* Badge/pill shadows */
className="shadow-sm shadow-primary/20"
```

---

## Border Radius

Global `--radius: 10px` base with semantic scaling:

| Class | Radius | Use Case |
|-------|--------|----------|
| **rounded-md** | 6px | Input focus ring, small elements |
| **rounded-lg** | 8px | Buttons, small cards |
| **rounded-xl** | 12px | Brutalist cards (legacy) |
| **rounded-2xl** | 16px | Cards, dialogs, large containers |
| **rounded-full** | 9999px | Badges, pills, avatars |

---

## Component Patterns

### Card Component

Clean, refined cards with soft shadows:

```tsx
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';

<Card className="refined-card">
  <CardHeader>
    <CardTitle>Title</CardTitle>
  </CardHeader>
  <CardContent>
    {/* Content */}
  </CardContent>
</Card>
```

**CSS:**
```css
.refined-card {
  border: 1px solid var(--border);
  background-color: var(--card);
  border-radius: 1rem;
  box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05);
}

.refined-card:hover {
  box-shadow: 0 4px 12px 0 rgba(0, 0, 0, 0.08);
}
```

### Button Hierarchy

```tsx
// Primary action (solid color)
<Button>Save Changes</Button>

// Secondary action (outline)
<Button variant="outline">Cancel</Button>

// Destructive action
<Button variant="destructive">Delete</Button>

// Ghost/minimal
<Button variant="ghost">Link-style button</Button>

// Special state (pressed)
<Button className="btn-pressed">Active State</Button>
```

### Badge Usage

```tsx
// Status indicator
<Badge variant="default">Active</Badge>

// Outlined label
<Badge variant="outline">Optional</Badge>

// Secondary indicator
<Badge variant="secondary">Inactive</Badge>

// Pill shape (auto-rounded)
<Badge className="rounded-full">Tag</Badge>
```

### Input Fields

```tsx
<Input
  placeholder="Enter text"
  className="border border-border"
/>

/* On focus: ring-2 ring-ring ring-opacity-50 */
```

---

## Page Layout Pattern

### Standard Header + Content Structure

```tsx
<div className="min-h-screen bg-background">
  {/* Sticky Header */}
  <div className="border-b border-border bg-card sticky top-0 z-10">
    <div className="container py-4">
      <h1 className="text-4xl font-bold mb-1">Page Title</h1>
      <p className="text-sm text-muted-foreground">Subtitle or description</p>
    </div>
  </div>

  {/* Main Content */}
  <div className="container py-6">
    <div className="space-y-6">
      {/* Cards, sections, etc */}
    </div>
  </div>
</div>
```

### Card Grid Pattern

```tsx
<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
  {items.map((item) => (
    <Card key={item.id} className="refined-card">
      <CardContent className="p-6">
        {/* Content */}
      </CardContent>
    </Card>
  ))}
</div>
```

---

## Dark Mode

All components automatically support dark mode via CSS variables.

**How it works:**
- `.dark` class on root element toggles dark mode
- All colors defined in `:root` and `.dark` CSS selectors
- Components inherit colors from CSS variables

**Testing dark mode:**
```
1. Toggle OS dark mode setting
2. Or set .dark class on document.documentElement
3. All colors adjust automatically
```

---

## Accessibility

### Color Contrast

- Primary text on background: **WCAG AA** (7:1+)
- Secondary text on background: **WCAG AA** (4.5:1+)
- Interactive elements: **WCAG AA** minimum

### Focus States

All interactive elements have visible focus rings:

```css
:focus-visible {
  outline: 3px solid var(--ring);
  outline-offset: 2px;
}
```

### Semantic HTML

Always use proper HTML semantics:

```tsx
// ✅ Correct
<h1>Page Title</h1>
<h2>Section Title</h2>
<button>Action</button>
<a href="/link">Link</a>

// ❌ Avoid
<div className="h1">Page Title</div>
<span onClick={...}>Action</span>
```

---

## Transitions & Animations

### Duration

Standard timing for consistency:

```css
transition: all 0.2s ease-in-out;  /* Default for all interactive elements */
```

### Common Patterns

```css
/* Color changes */
transition: color 0.2s ease-in-out;

/* Transform */
transition: transform 0.2s ease-in-out;

/* Shadow on hover */
transition: box-shadow 0.2s ease-in-out;

/* Opacity */
transition: opacity 0.2s ease-in-out;
```

---

## Removed/Deprecated Patterns

### ❌ Don't Use (Brutalist Remnants)

```tsx
// OLD - NEVER use
<Card className="brutalist-card border-4">...</Card>
<div className="border-b-4 border-border">...</div>
<Button className="border-2 border-border">...</Button>
<h1 className="text-3xl">...</h1>

// NEW - Use instead
<Card className="refined-card">...</Card>
<div className="border-b border-border">...</div>
<Button variant="outline">...</Button>
<h1 className="text-4xl">...</h1>
```

---

## Implementation Checklist for New Features

When building new pages or components, follow this checklist:

- [ ] Page title uses `<h1 className="text-4xl font-bold">`
- [ ] Section titles use `<h2 className="text-3xl font-bold">`
- [ ] Cards use `className="refined-card"`
- [ ] Borders are `border border-border` or `border-b border-border` (never thick)
- [ ] Buttons use component defaults (no manual border-2)
- [ ] Spacing uses semantic units (space-y-4, gap-2, etc)
- [ ] Shadows use soft, layered approach (shadow-sm shadow-black/5)
- [ ] Dark mode tested and working
- [ ] Focus states visible on interactive elements
- [ ] Text contrast meets WCAG AA
- [ ] Responsive design tested on mobile/tablet/desktop

---

## Resources

- **Colors**: Define in `client/src/index.css` (CSS variables)
- **Components**: shadcn/ui library in `client/src/components/ui/`
- **Icons**: Lucide React library
- **CSS Framework**: Tailwind CSS v4
- **Typography**: Space Grotesk (display), Inter (body), JetBrains Mono (monospace)

---

## Version History

### v2.0 (2026-02-06)
- **Added**: Typography scale tokens (h1-h6)
- **Removed**: .brutalist-card (deprecated, aliased to .refined-card)
- **Removed**: All thick borders (border-4, border-b-4)
- **Updated**: All h1 tags to text-4xl (40px) for consistency
- **Updated**: Button styling (removed manual border-2)
- **Improved**: Soft shadow system, subtle depth
- **Created**: DESIGN_SYSTEM.md documentation

### v1.0 (Previous)
- Transitioned from brutalism to modern refined aesthetic
- Telegram-style UI with custom components
