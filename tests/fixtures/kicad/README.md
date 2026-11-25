# KiCad footprints

Footprints from the KiCad footprint library, <https://gitlab.com/kicad/libraries/kicad-footprints>, licensed CC BY-SA 4.0 with the KiCad libraries exception. `tests/test_pinout_faces.py` reads their pad positions as the reference for where each connector's contacts sit.

Each is a vertical-mount footprint: the connector stands on the board with its mating face up, so the pads seen from above are laid out as the mating face is seen from the front.

- `Jack_XLR_Neutrik_NC3FAV_Vertical.kicad_mod`: Neutrik NC3FAV, 3-pole female XLR.
- `Jack_XLR_Neutrik_NC3MAV_Vertical.kicad_mod`: Neutrik NC3MAV, 3-pole male XLR.
- `DSUB-9_Pins_Vertical_P2.77x2.84mm.kicad_mod`: 9-way D-sub, male.
