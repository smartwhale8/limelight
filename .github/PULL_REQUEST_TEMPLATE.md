# Pull request

## What this changes

<!-- One or two sentences. Link an issue if there is one. -->

## Why

<!-- The problem this solves, or the behaviour it corrects. -->

## Verification

<!-- What you ran, and against what. If you tested on a device, name the model and
     firmware version, because that is what makes a hardware claim checkable. -->

- [ ] `pytest` passes
- [ ] `ruff check .` passes
- [ ] Tested against real hardware — model and firmware:

## API impact

- [ ] No change to the HTTP API
- [ ] Additive only: new fields or endpoints, nothing removed or repurposed
- [ ] Breaking: removes or changes existing behaviour — **needs discussion first**, see [docs/API.md](../docs/API.md)

## Checklist

- [ ] Tests added or updated, and they run without hardware
- [ ] Documentation updated where user-visible: [API.md](../docs/API.md) for endpoints, [PROTOCOL.md](../docs/PROTOCOL.md) for device commands, the README table for a new device
- [ ] `CHANGELOG.md` entry added under `Unreleased`
- [ ] No token, MAC address, network name, or personal IP address anywhere in the diff
- [ ] Layering respected: nothing above `limelight/drivers/` names a device, a miIO command, or a model string

## For a new device driver

- [ ] Model identifier and display name declared
- [ ] Capability set matches what the hardware actually does, with nothing overclaimed
- [ ] Registered via `@register` and imported in `limelight/drivers/__init__.py`
- [ ] Command surface documented in the module docstring
- [ ] Any device behaviour found is documented with the values observed, keeping the measurement separate from the interpretation
- [ ] Added to the supported devices table in the README

## Notes for the reviewer

<!-- Anything surprising, any decision you were unsure about, anything you deliberately
     left out of scope. -->
