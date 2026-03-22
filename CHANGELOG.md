# Changelog

## 1.0.0

Initial release.

### Effects

- **Fire** — terminal conflagration with heat simulation, ember system, and simplex noise smoke
- **Invaders** — bombardment phase followed by full alien invasion with procedural sprites
- **Grove** — nature reclaims the terminal: grass, flowers, trees, birds, butterflies
- **Microbes** — colorful organisms dash along curved Catmull-Rom spline paths
- **Paperclips** — exponential paperclip replication consumes the screen, then the world
- **Mascot** — Clippy watches from the corner (demo-only standalone overlay)

### Features

- Unified effect lifecycle with mascot overlay (WATCHING -> IMMINENT -> ACTIVE -> CACKLING)
- Cursor shake detection (5 L+R reversals within 2s) for skipping idle or cancelling effects
- Effect cycling with anti-repeat shuffle in live mode
- Demo mode with VS Code-style IDE background template
- tattoy plugin protocol: line-delimited JSON on stdin/stdout

### Infrastructure

- Zero third-party dependencies (stdlib only, Python 3.10+)
- Golden file testing for wire format correctness
- Property-based testing for coordinate bounds and color ranges
- 495 tests across 15 test files
- install.sh / uninstall.sh for easy deployment
- PEP 561 py.typed marker
