# DXF block valve visibility

Imported block outlines were retained under virtual `块·` layers but rendered only in the dashboard's initially hidden CAD reference overlay. In the import preview, hiding reference lines also hid the outlines of devices the user had selected. Polylines on selected pipe layers remained visible, explaining the difference between the two drawing methods.

Block outlines now have a separate, initially visible “CAD 块符号” overlay. Its switch is independent of reference lines and keeps its state when data refreshes. The import preview and alignment point picker use the selected block mapping for outlines. Small block outlines keep eight decimal places in map coordinates to prevent centimetre-scale vertices from collapsing into one rounded point. Symbols remain separate from pipe inventory.

Device suggestions recognize common Chinese valve names and names such as `GV_50`, `AV-25`, `QCV_15`, and `WD_40`, with separators normalized for type recognition. Unrecognized blocks remain available for explicit mapping; their retained geometry is still displayed.

The live database contains one retained drawing, `Zone 2-3-7.dxf`: four layers, 764 paths and 249 imported pipes. Its retained source contains polylines/arcs and no INSERT candidates. An isolated fixture reconstructed those exact paths and added seven block instances, including rotation, nonuniform scaling, nesting, an array and an anonymous block. The original and augmented drawings both imported as 249 pipes; six selected devices were created with attributes intact, while all nine block outline paths appeared independently of reference lines. Phone and desktop browser checks verified preview, full import, map display and toggles.

Validation: 83 DXF/backend checks passed (one existing external fixture skip), 141 operations tests passed and 125 JavaScript tests passed. Older alignment test fixtures were updated for the existing frozen-preview submission key and explicit direct-import review; a before/after baseline confirmed those failures predated this change. No schema migration or production data backfill is required.
