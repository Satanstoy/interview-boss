# Fix db/operations.py Reverse Dependency

**Date**: 2026-06-29
**Status**: Approved
**Scope**: Move two utility functions to fix architecture boundary violation

## Problem

`db/operations.py` (database layer) imports from `services/utils.py` (service layer):

```python
from app.services.utils import _extract_url_signature, normalize_category
```

This violates the `Routers → Services → Core/DB` dependency direction.

## Solution

Move `_extract_url_signature` and `normalize_category` to `db/utils.py`. Update `services/utils.py` to re-export them for backward compatibility.

**Files:**
- Create: `backend/app/db/utils.py` — contains the two functions
- Modify: `backend/app/db/operations.py` — import from `db.utils` instead of `services.utils`
- Modify: `backend/app/services/utils.py` — re-export from `db.utils`

**Consumers (no change needed):**
- `services/submit_service.py` imports `normalize_category` from `services.utils` (still works via re-export)
- `routers/analytics.py` imports `normalize_category` from `services.utils` (still works)
- `routers/questions_pkg/mutations.py` imports `normalize_category` from `services.utils` (still works)
