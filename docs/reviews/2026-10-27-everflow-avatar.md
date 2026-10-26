# Everflow assistant identity

The supplied transparent water-sprite PNG replaces the assistant's SVG in the map
launcher, chat header, welcome page and response status avatar. The source artwork
is preserved byte-for-byte (SHA-256
`647929de8a1638982e84bd0b8fbc21a3e45b1ec55be1b1cdebb192ff8c870b1b`).
Small avatars crop the face in CSS; the welcome page shows the complete character.
The same cached static asset is reused throughout the interface.

The assistant is named Everflow. The welcome heading is
“Everflow — Your Intelligent Irrigation Companion”, with the concise Chinese
greeting “你好，我是 Everflow。今天需要什么帮助？” Header, launcher, composer
labels and accessible names use the same identity. Existing preparation/tool/stream
status feedback remains, with a gentle welcome animation honoring reduced-motion
preferences. The dashboard versions the updated JavaScript and stylesheet and
supplies the static image URL through its script element.

Validation: JavaScript syntax and whitespace checks passed, along with all nine
existing AI chat core regressions. Browser checks used the actual dashboard and
chat assets with the disposable local fixture and synthetic responses. Verified
the desktop floating chat, 390-pixel phone layout, Chinese/English wrapping,
launcher/header/welcome artwork and preparation state. No model calls or production
business operations were used for these checks. This change needs no migration.
