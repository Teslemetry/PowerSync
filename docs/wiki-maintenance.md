# Maintaining the Home Assistant wiki

The wiki configuration reference follows `custom_components/power_sync/config_flow.py`, its actual rendered schemas, the English labels, battery connection profiles and supported runtime controls. Do not generate a guide from method names or `strings.json` alone: legacy routes, conditional fields and grouped schemas can differ.

`docs/wiki-configuration-map.json` records the checked integration/wiki/client refs, all setup/options step destinations or exclusions, field-label occurrences, battery/provider coverage, menu labels and compatibility anchors. Its source signatures are deliberately conservative: changes to configuration, discovery, control surfaces or labels require a documentation-impact review. They are not runtime branch-coverage or hardware proof.

## Checks

Source review guard, used by CI without a wiki checkout or network access:

```bash
python3.12 scripts/check_wiki_docs.py --source-only
```

Full local documentation check:

```bash
python3.12 scripts/check_wiki_docs.py --wiki /path/to/PowerSync.wiki
```

The full check validates local pages/images/anchors, preserved public anchors, Home/sidebar reachability, every step destination/exclusion, recorded field labels and all registered profiles/providers. It flags known obsolete setup instructions. It does not visit external sites, contact HA, authenticate to providers or issue controls.

## Changing configuration or controls

1. Review the source change against both initial setup and existing-install options. Follow helpers and actual grouping; inspect save/live/reload effects and errors, not only the field declaration.
2. Update the canonical wiki reference. Keep shared feature behaviour in one place and qualify battery capabilities by connection method. Keep configuration, entities/services, app actions and physical outcomes separate.
3. Update destinations, labels, profile/provider mappings and any explicit exceptions in the manifest. Do not add a coverage waiver merely to make a check pass. Missing UI labels or dropped fields need a source issue and accurate current-behaviour documentation.
4. Preserve old page URLs and anchors with useful summaries/links when moving sections. Keep Home and sidebar entry points synchronized.
5. After that review, acknowledge the source signatures:

   ```bash
   python3.12 scripts/check_wiki_docs.py --refresh-source-signatures
   ```

6. Run source and full wiki checks, relevant existing source-extraction regressions, and visual checks on a test HA instance when needed. Record which checks were actually executed. An AST/source-string test cannot establish a physical capability.
7. Before publishing, re-fetch integration/wiki refs, reconcile intervening edits and rerun affected checks. Publication of a wiki does not publish an integration fix or install a running version.

The initial rebuild documents known v2.12.1411 source/UI limitations explicitly. A future fix must update the affected limitation and save/availability instructions only after verifying its behaviour. Mobile breadcrumbs require a checked client source/version; an HA field does not guarantee a matching mobile control.
