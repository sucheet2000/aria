# Design System Specification: Cyber-Organic Minimalism

## 1. Overview & Creative North Star: "The Ethereal Core"
This design system is built to bridge the gap between cold artificial intelligence and organic human intuition. Our Creative North Star is **"The Ethereal Core"**—a philosophy where the interface does not feel like a rigid machine, but like a living, breathing entity suspended in a deep digital void.

To break the "template" look of modern SaaS, we reject the standard grid in favor of **intentional asymmetry** and **atmospheric depth**. We achieve this through:
*   **Dimensional Overlap:** UI elements should rarely sit side-by-side on a flat plane; they should float, overlap, and bleed into one another.
*   **The Depth of Space:** We use wide tracking in typography and generous white space (defined by our spacing scale) to create a sense of vastness.
*   **Kinetic Light:** Interfaces are not static. Use the indigo accents not just as colors, but as "light sources" that cast soft glows on surrounding surfaces.

---

## 2. Color & Surface Architecture
Our palette transitions from the absolute void of deep space to the vibrant energy of AGI processing.

### The "No-Line" Rule
**Strict Mandate:** Traditional 1px solid borders for sectioning are prohibited. Boundaries must be defined through background color shifts or tonal transitions.
*   **Instead of a line:** Place a `surface_container_high` element against a `surface` background. The subtle 2-3% contrast shift is all the eye needs to perceive a container.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers of frosted glass. 
*   **Level 0 (The Void):** `surface` (#0e0e12) is the canvas.
*   **Level 1 (The Foundation):** `surface_container_low` (#131317) for large content areas.
*   **Level 2 (The Interactive):** `surface_container_highest` (#25252b) for active cards or interactive modules.

### The "Glass & Gradient" Rule
To create a premium feel, floating elements (modals, popovers) must use **Glassmorphism**:
*   **Background:** `surface_variant` at 60% opacity.
*   **Effect:** `backdrop-filter: blur(20px)`.
*   **Signature Texture:** Main CTAs should use a linear gradient from `primary` (#a3a6ff) to `primary_dim` (#6063ee) at a 135° angle to provide a "soulful" luminosity.

---

## 3. Typography: Editorial Authority
We utilize a high-contrast typographic scale to separate high-level narrative from technical data.

*   **Display & Headlines (Manrope):** Chosen for its wide, geometric stance. Use `display-lg` for AGI-generated statements to create an authoritative, editorial feel.
*   **Body & Titles (Inter):** The workhorse. Inter provides maximum legibility within the "frosted" glass containers. Use `body-md` for user inputs and standard descriptions.
*   **Labels & Data (Space Grotesk):** Our "Technical Layer." All system stats, timestamps, and AGI metadata must use `label-md` in Space Grotesk. This mono-spaced influence signals precision.

---

## 4. Elevation & Depth: Tonal Layering
We do not use shadows to simulate "drop"; we use light to simulate "presence."

*   **The Layering Principle:** Depth is achieved by "stacking" the surface-container tiers. Place a `surface_container_lowest` card on a `surface_container_low` section to create a soft, natural "recessed" look.
*   **Ambient Shadows:** For floating avatars or primary prompts, use an extra-diffused shadow: `box-shadow: 0 24px 48px rgba(99, 102, 241, 0.08)`. Note the indigo tint in the shadow—this mimics the light cast by the AGI itself.
*   **The "Ghost Border" Fallback:** If accessibility requires a border, use the `outline_variant` token at **15% opacity**. It should be felt, not seen.
*   **Glowing Borders:** For "Active" states, use a 1px inner-glow using the `primary_fixed` token with a `4px` blur. This creates a "cyber-organic" energy pulse.

---

## 5. Components & Primitives

### Buttons (The Kinetic Triggers)
*   **Primary:** High-grade indigo gradient (`primary` to `primary_dim`). Roundedness: `full`. No border.
*   **Secondary:** Glassmorphic. Background: `surface_container_high` at 40% opacity + blur.
*   **Tertiary:** Text-only using `primary_fixed_dim`. Use `label-md` typography.

### Input Fields (The Conversation Portal)
*   **Styling:** Forbid traditional "box" inputs. Use `surface_container_highest` with a `24px (lg)` corner radius. 
*   **States:** On focus, the background stays the same, but a subtle "Ghost Border" of `primary` at 20% opacity appears.

### Cards & Lists (The Stream)
*   **No Dividers:** Forbid the use of line dividers between list items. Use `spacing-6` (2rem) of vertical white space or a subtle hover shift to `surface_bright`.
*   **Curvature:** All containers must use a minimum of `md` (1.5rem/24px) or `lg` (2rem/32px) corner radius to maintain the "Organic" half of the theme.

### Signature Component: The "Aura" Chip
A custom chip for AGI status. It uses a `secondary_container` background with a soft `surface_tint` outer glow. Typography must be `label-sm` (Space Grotesk) to emphasize the technical nature of the status.

---

## 6. Do’s and Don’ts

### Do:
*   **Do** allow background "blobs" of Indigo to peak through glass layers.
*   **Do** use asymmetrical margins (e.g., 10% left, 15% right) for hero sections to create a custom editorial feel.
*   **Do** utilize micro-interactions: elements should "lift" (shift upward by 4px) and increase their backdrop-blur value when hovered.

### Don't:
*   **Don't** use pure white (#FFFFFF). Use `on_surface` (#f3eff6) for all text to prevent harsh "vibration" against the midnight background.
*   **Don't** use 90-degree sharp corners. This violates the "Organic" requirement.
*   **Don't** use standard Material shadows. Shadows must always be low-opacity and indigo-tinted.
*   **Don't** use solid "drawer" menus. Use glassmorphic overlays that allow the user to see the AGI avatar behind the navigation.