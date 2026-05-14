# SP12b — Interview Page Branding

## Overview

Adds project-level branding to the public `VoiceInterview` page: a header image and a two-colour palette (primary/text). Branding is stored in project settings, uploaded via a dedicated endpoint, and included in the interview session response so the public page can apply it without knowing the project slug.

---

## Section 1 — Backend

### ProjectSettings extension

**File:** `api/models.py` (or wherever `ProjectSettings` is defined)

Add three fields with safe defaults:

```python
brand_header_image_url: str = ""
brand_primary_color: str = "#0d9488"   # teal brand default
brand_text_color: str = "#1f2937"      # gray-800 default
```

These are persisted in the existing `project_config` JSON column alongside all other settings fields.

### Image upload endpoint

**File:** `api/routers/projects.py`

```
POST /api/projects/{slug}/branding/image
Content-Type: multipart/form-data
Field: file (image/png, image/jpeg, image/webp — max 2 MB)
```

Steps:
1. Authenticate (JWT required — consultant only)
2. Validate `slug` exists
3. Validate file content-type is image/* and size ≤ 2 MB
4. Save to `projects/{slug}/assets/header.{ext}` (create `assets/` dir if absent)
5. Patch `brand_header_image_url` in project config to `/api/projects/{slug}/branding/image`
6. Return `{"url": "/api/projects/{slug}/branding/image"}`

### Image serve endpoint

```
GET /api/projects/{slug}/branding/image
```

Serves the stored file with correct `Content-Type`. Returns 404 if no image uploaded. No auth required (public page needs it).

### Session response extension

**File:** `api/services/interview_service.py` — `get_session_with_script`

After reading project config, append a `branding` key to the returned dict:

```python
branding = {
    "header_image_url": config.get("brand_header_image_url", ""),
    "primary_color": config.get("brand_primary_color", "#0d9488"),
    "text_color": config.get("brand_text_color", "#1f2937"),
}
return {"session": session_dict, "script": script, "branding": branding}
```

Project config is read from `project_config` column — use existing `fetch_project_config` helper.

---

## Section 2 — Frontend

### Settings page branding section

**File:** `ui/src/pages/Settings.tsx`

Add a "Interview Branding" card below existing settings fields:

- **Header image**: file input (accepts `image/*`), preview of current image if set, upload button POSTs multipart to `/api/projects/{slug}/branding/image`
- **Primary colour**: `<input type="color">` bound to `brand_primary_color`, saved via existing PATCH `/api/projects/{slug}/settings`
- **Text colour**: `<input type="color">` bound to `brand_text_color`, same save path

### VoiceInterview page

**File:** `ui/src/pages/VoiceInterview.tsx`

The fetch response now includes `branding`. Apply it:

```typescript
// In fetchSession(), after parsing data:
setBranding(data.branding ?? null)

// Render: top of every phase (loading, ready, interviewing, complete):
{branding?.header_image_url && (
  <img src={branding.header_image_url} alt="" className="w-full max-h-24 object-contain mb-6" />
)}
```

Primary colour applied via inline style on:
- Progress bar fill: `style={{ backgroundColor: branding?.primary_color }}`
- Done button: `style={{ backgroundColor: branding?.primary_color }}`
- Start Interview button: `style={{ backgroundColor: branding?.primary_color }}`

Text colour applied via inline style on:
- Heading (`h1`): `style={{ color: branding?.text_color }}`

Fall back to Tailwind classes when `branding` is null (existing behaviour unchanged).

### New TypeScript type

**File:** `ui/src/types.ts`

```typescript
export interface InterviewBranding {
  header_image_url: string
  primary_color: string
  text_color: string
}
```

---

## Section 3 — Files affected

| File | Change |
|---|---|
| `api/models.py` | Add 3 branding fields to `ProjectSettings` |
| `api/routers/projects.py` | Add `POST` + `GET` `/branding/image` endpoints |
| `api/services/interview_service.py` | Append `branding` to `get_session_with_script` response |
| `ui/src/pages/Settings.tsx` | Add branding card (image upload + colour pickers) |
| `ui/src/pages/VoiceInterview.tsx` | Read + apply `branding` from session response |
| `ui/src/types.ts` | Add `InterviewBranding` type |
| `tests/test_projects_router.py` | 2 tests: image upload + branding in session response |

---

## Task breakdown (3 tasks)

**Task 1 — Backend:** ProjectSettings fields + image upload/serve endpoints + session response extension + 2 tests

**Task 2 — Frontend settings:** Branding card in Settings.tsx (image upload + colour pickers)

**Task 3 — Frontend interview:** Apply branding in VoiceInterview.tsx (header image + inline colour styles)
