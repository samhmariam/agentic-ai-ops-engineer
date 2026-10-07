# Products template — copy & edit for Task 1

`make load-data` ingests every `data/products/*.json` that matches the
schema in `src/ingestion/watcher.py::REQUIRED_FIELDS`:

```text
product_id, name, category, brand, price, description,
specifications, care_instructions
```

Below are five JSON skeletons spanning the four product categories
(`paddles`, `balls`, `accessories`, `apparel`). Each block has
`// FILL IN: …` comments for the fields you must populate. Copy a
block into `data/products/<product_id>.json` (drop the comments — JSON
forbids them), edit the placeholders, then re-run `make load-data` and
issue an unambiguous query through `POST /query` to confirm retrieval
returns your new product.

> **Caps to respect** (from `watcher.py`): file ≤ 256 KB,
> `name` ≤ 200 chars, `description` ≤ 4000 chars, `care_instructions`
> ≤ 2000 chars, `product_id` / `category` / `brand` ≤ 64 chars.

---

## 1) Paddle

```json
{
  "product_id": "prod_026_<short_slug>",         // FILL IN: lowercase slug, e.g. "prod_026_diadem_warrior"
  "name": "<Brand> <Model>",                     // FILL IN: e.g. "Diadem Warrior"
  "category": "paddles",
  "brand": "<Brand>",                            // FILL IN
  "price": 0.00,                                 // FILL IN: USD float, e.g. 159.99
  "description": "<one-paragraph customer-facing overview>",
  "specifications": {
    "weight": "<oz>",                            // FILL IN: e.g. "8.0 oz"
    "grip_size": "<in>",                         // FILL IN: e.g. "4.25 in"
    "face_material": "<face material>",          // FILL IN
    "core": "<core construction>",               // FILL IN
    "shape": "<elongated|widebody|hybrid>",      // FILL IN
    "length": "<in>",
    "width": "<in>"
  },
  "care_instructions": "<plain-language care tips, ~1–2 sentences>"
}
```

## 2) Ball

```json
{
  "product_id": "prod_027_<short_slug>",
  "name": "<Brand> <Model>",
  "category": "balls",
  "brand": "<Brand>",
  "price": 0.00,
  "description": "<paragraph: indoor/outdoor, intended use, materials>",
  "specifications": {
    "hole_count": 0,                             // FILL IN: 26 (indoor) or 40 (outdoor)
    "weight": "<oz>",
    "material": "<polymer / rubber blend>",
    "color": "<primary color>",
    "pack_size": 0                               // FILL IN: balls per pack
  },
  "care_instructions": "<storage + replacement guidance>"
}
```

## 3) Accessory (bag)

```json
{
  "product_id": "prod_028_<short_slug>",
  "name": "<Brand> <Model>",
  "category": "accessories",
  "brand": "<Brand>",
  "price": 0.00,
  "description": "<paragraph: who is this for, what does it carry>",
  "specifications": {
    "type": "<sling|backpack|duffel|tote>",
    "paddle_capacity": 0,                        // FILL IN: how many paddles fit
    "compartments": 0,                           // FILL IN
    "material": "<exterior fabric>",
    "dimensions": "<H x W x D>"
  },
  "care_instructions": "<cleaning + storage tips>"
}
```

## 4) Accessory (court shoes)

```json
{
  "product_id": "prod_029_<short_slug>",
  "name": "<Brand> <Model>",
  "category": "accessories",
  "brand": "<Brand>",
  "price": 0.00,
  "description": "<paragraph: court use case, fit, traction story>",
  "specifications": {
    "upper_material": "<mesh / synthetic leather>",
    "midsole": "<EVA / cushioning tech>",
    "outsole": "<rubber compound + tread pattern>",
    "size_range": "<e.g. 7–13 US M>",
    "weight_per_shoe": "<oz>"
  },
  "care_instructions": "<wipe-down + drying recommendations>"
}
```

## 5) Apparel

```json
{
  "product_id": "prod_030_<short_slug>",
  "name": "<Brand> <Item>",                      // FILL IN: e.g. "Engage Court Polo"
  "category": "apparel",
  "brand": "<Brand>",
  "price": 0.00,
  "description": "<paragraph: cut, performance properties, recycled content if any>",
  "specifications": {
    "garment_type": "<polo|tee|short|skirt>",
    "material": "<fiber blend, e.g. 100% recycled polyester>",
    "fit": "<athletic|relaxed>",
    "size_range": "<XS–XXL>",
    "color_options": ["<color1>", "<color2>"],
    "moisture_wicking": true                     // FILL IN: true/false
  },
  "care_instructions": "<wash + dry guidance>"
}
```

---

## Verifying retrieval after `make load-data`

```bash
cd project/starter
make load-data
make serve   # in another terminal, then:

curl -X POST http://localhost:8080/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "Tell me about <something unambiguous from your new product>"}' | jq .sources
```

If your new product's `description` text is in the `sources` array,
retrieval is working.
