# REST quick reference

All under `/api/v1`, header `Authorization: Bearer <token>`. JSON in and out unless noted.

| Need | Call |
|---|---|
| Search items | `GET /items?q=&category=&color=&season=&occasion=&brand=&style=&status=&sort=&limit=&offset=` |
| One item | `GET /items/{id}` · edit `PATCH /items/{id}` · delete `DELETE /items/{id}` |
| Create item | `POST /items {name, category, subcategory, colors[], seasons[], occasions[], brand, size, ...}` |
| Mark worn | `POST /items/{id}/wear` |
| Photos onto an item | `POST /items/{id}/photos` multipart `files`, `role` (shows/worn/tag/receipt/detail) |
| Photos | `GET /photos?kind=&person=me&source=real|ai&item_id=` · `GET /photos/{id}` |
| Link photo | `POST /photos/{id}/links {item_id, role, bbox?}` · `PATCH|DELETE /links/{id}` |
| Turn a picture | `POST /photos/{id}/rotate {degrees}` (whole photo, boxes follow) · `POST /links/{id}/rotate {degrees}` (only the item's crop / cut-out); degrees 90, 180, 270 or -90, clockwise |
| Facet counts | `GET /facets?<same filters>` |
| Import | `POST /batches {note, hints, auto_commit: none|confident|all}` → `upload_url` |
| Upload | `POST /batches/{id}/photos` multipart `files` (or the one-time `upload_url`, no auth) |
| Review | `GET /batches/{id}` · `PATCH /proposals/{id} {data, match_item_id}` · `POST /proposals/merge {ids}` |
| Commit | `POST /batches/{id}/commit {which: confident|all}` or `{proposals: [ids]}` |
| Studio | `GET /studio` · `POST /studio/jobs {template, item_ids, extra}` · `POST /studio/cancel {ids}|{all_queued:true}` |
| Try on | `POST /studio/tryon {photo_id, item_ids, options: {background, scene, keep_rest, light, smooth, crop, transparent, cover, variants, extra}}` → `{jobs}` |
| Queue control | `PATCH /studio/prefs {paused: true}` · `POST /studio/jobs/{id}/retry` · `POST /studio/backfill {templates}` |
| Taxonomy | `GET /taxonomy` |

Item fields: `name, category, subcategory, colors[{name,hex}], seasons[], occasions[], styles[], tags[],
brand, size, material, pattern, fit, status (active|stored|lent|donated|sold|discarded), location, notes,
store, store_url, purchase_date, price, original_price, currency, gifted_by, favorite`.
