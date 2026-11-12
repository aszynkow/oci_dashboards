# Architecture diagram

The README's one-page diagram shows the Activity event pipeline and optional Coverage inventory flow implemented by this repository. It includes the existing Function subnet, hourly scheduler, private OCIR image, separate Log Analytics sources/groups, custom metrics, invocation logs and native Console dashboards. The lower panels explain home-region IAM and the operator-run Python/Terraform workflow with separate OCIR/infrastructure state.

- [PNG, 2880 × 1620](backup-dashboard-architecture.png)
- [Editable standalone SVG](backup-dashboard-architecture.svg)
- [Existing diagram URL](backup-activity-design.png): identical PNG retained for existing documentation links.
- [Alternate Graphviz overview](backup-activity-design.dot): same architecture, simplified layout; the branded PNG is rendered from the SVG composition.

The diagram is intentionally free of live OCIDs, usernames, credentials and compartment names. Coverage is optional in the repository and enabled in the inspected deployment. Service cards show implemented architecture, not a live health assertion. A selected root compartment in the UI does not expand inventory/capture scope. No networking path, gateway or CIDR is invented. The Function uses an existing subnet with API egress supplied by the operator.

## Artwork and regeneration

Artwork was extracted from the local `OCI_Icons.pptx`, **OCI Architecture Diagram Toolkit v23.1 (March 2023)**. Original vector shapes and the toolkit's Redwood palette are reused. See [catalog provenance and slide mapping](oci-icons/provenance.json). Resource Scheduler uses the catalog's generic Other Oracle Cloud Service icon because this catalog has no dedicated scheduler glyph; Console window frames are generic diagram notation. Oracle icon artwork remains attributable to Oracle and/or its affiliates.

From the repository root, with `rsvg-convert` available (librsvg):

```bash
python scripts/render_architecture.py
```

The renderer uses the committed service SVG assets, needs no access to the original catalog, performs no OCI calls, and refreshes both PNG paths. Edit the layout/text in the renderer, then render and visually inspect the PNG. The generated SVG is also directly editable in vector tools. No image-generation service or external font dependency is required; Arial with sans-serif fallbacks follows the catalog guidance.
