# Brand/Supplier Connection & Product Contribution Lifecycle Documentation

This document provides a comprehensive analysis of the two core lifecycles implemented in the DPP Guard Backend system:
1. **Brand/Supplier Connection Lifecycle** - How brands connect with suppliers
2. **Product/Product Contribution Lifecycle** - How products are created and suppliers contribute technical data

---

## Table of Contents

1. [Brand/Supplier Connection Lifecycle](#brandsupplier-connection-lifecycle)
2. [Product/Product Contribution Lifecycle](#productproduct-contribution-lifecycle)
3. [Key Data Models](#key-data-models)
4. [State Transitions](#state-transitions)
5. [API Endpoints Reference](#api-endpoints-reference)

---

## Brand/Supplier Connection Lifecycle

### Overview

The Brand/Supplier connection lifecycle manages the B2B relationship between Brands (buyers) and Suppliers (manufacturers). It uses a dual-table architecture:
- **TenantConnection**: The "handshake" record (source of truth for relationship status)
- **SupplierProfile**: The "address book" entry (denormalized view for fast reads)

### Architecture Pattern

The system uses a **denormalization pattern** where:
- `TenantConnection` is the **source of truth** for connection state
- `SupplierProfile` maintains **denormalized fields** (status, slug, retry_count) for performance
- Both tables are kept in sync during state changes

### Lifecycle Flow

#### Phase 1: Brand Initiates Connection

**Endpoint**: `POST /api/v1/supplier-profiles/`

**Service Method**: `SupplierProfileService.add_profile()`

**Two Connection Methods:**

1. **Connect to Existing Supplier** (via `public_handle`)
   - Brand provides the supplier's platform slug
   - System resolves the supplier tenant from the directory
   - Creates connection with `target_tenant_id` set immediately

2. **Invite New Supplier** (via `invite_email`)
   - Brand provides supplier email address
   - System generates secure invitation token
   - Creates connection with `target_tenant_id = None` (will be linked during registration)

**Execution Steps:**

```
1. Validate uniqueness of supplier name within brand's address book
2. Resolve target tenant (if public_handle provided)
   - Query Tenant table by slug
   - Validate tenant type is SUPPLIER
3. Create TenantConnection (THE HANDSHAKE)
   - requester_tenant_id = brand.id
   - target_tenant_id = resolved tenant ID (or None for email invite)
   - type = RelationshipType.SUPPLIER
   - status = ConnectionStatus.PENDING
   - invitation_token = secure random token (32 bytes)
   - invitation_email = email (if provided)
   - request_note = optional message
   - retry_count = 0
4. Create SupplierProfile (THE ADDRESS BOOK ENTRY)
   - tenant_id = brand.id
   - connection_id = connection.id (FK link)
   - name, description, location_country, contact info
   - Denormalized fields:
     * supplier_tenant_id = target_tenant_id (or None)
     * connection_status = PENDING
     * slug = target tenant slug (or None)
     * retry_count = 0
5. Send invitation email (mock in current implementation)
   - Link format: {public_dashboard_host}/register?token={invitation_token}
6. Audit log creation
```

**Key Constraints:**
- Either `public_handle` OR `invite_email` must be provided (mutually exclusive)
- Supplier name must be unique within brand's address book
- Target tenant must be type SUPPLIER

#### Phase 2: Supplier Registration & Token Linking

**Endpoint**: `POST /api/v1/users/register`

**Service Method**: `UserService.create_user()`

**When a supplier registers with an invitation token:**

```
1. User creates account with invitation_token or matching email
2. System creates:
   - User record
   - Tenant record (SUPPLIER type)
   - TenantMember (owner membership)
3. System searches for pending connections:
   - WHERE invitation_token = token OR invitation_email = email
   - AND status = PENDING
4. For each matching connection:
   a. Update TenantConnection:
      * target_tenant_id = new_tenant.id
      * status remains PENDING (not ACTIVE yet!)
   b. Update SupplierProfile:
      * supplier_tenant_id = new_tenant.id
      * slug = new_tenant.slug
   c. Audit log on requester's (brand's) timeline
```

**Important**: Registration only **links** the connection; it does **not** activate it. The supplier must still accept the connection request.

#### Phase 3: Supplier Accepts/Declines Connection

**Endpoint**: `POST /api/v1/tenant-connections/requests/{connection_id}/respond`

**Service Method**: `TenantConnectionService.respond_to_request()`

**Execution Steps:**

```
1. Validate user is the target tenant
2. Fetch TenantConnection by connection_id
3. If ACCEPT:
   - connection.status = ACTIVE
   - connection.invitation_token = None (consume token)
   - Sync SupplierProfile:
     * connection_status = ACTIVE
     * supplier_tenant_id = target_tenant.id
     * slug = target_tenant.slug
4. If DECLINE:
   - connection.status = REJECTED
   - Sync SupplierProfile:
     * connection_status = REJECTED
5. Audit log on target tenant's timeline
```

**State Transition:**
- `PENDING` → `ACTIVE` (accept)
- `PENDING` → `REJECTED` (decline)

#### Phase 4: Reinvitation (Optional)

**Endpoint**: `POST /api/v1/tenant-connections/suppliers/{profile_id}/reinvite`

**Service Method**: `TenantConnectionService.reinvite_supplier()`

**When to Use:**
- Connection status is `PENDING` or `REJECTED`
- Retry count < 3
- Brand wants to resend invitation

**Execution Steps:**

```
1. Fetch SupplierProfile and linked TenantConnection
2. Validate status is PENDING or REJECTED
3. Validate retry_count < 3
4. Update TenantConnection:
   - status = PENDING (reset if was REJECTED)
   - retry_count += 1
   - invitation_token = new secure token (rotate for security)
   - invitation_email = updated email (if provided)
   - request_note = new note (if provided)
5. Sync SupplierProfile:
   - connection_status = PENDING
   - retry_count = connection.retry_count
   - invitation_email = updated email
6. Send new invitation email
7. Audit log
```

**Constraints:**
- Maximum 3 retry attempts
- Can only reinvite if status is PENDING or REJECTED

#### Phase 5: Disconnection (Suspension)

**Endpoint**: `DELETE /api/v1/supplier-profiles/{profile_id}`

**Service Method**: `SupplierProfileService.disconnect_supplier()`

**Execution Steps:**

```
1. Validate profile belongs to brand
2. Fetch linked TenantConnection
3. Update TenantConnection:
   - status = SUSPENDED
   - invitation_token = None (invalidate pending tokens)
4. Sync SupplierProfile:
   - connection_status = SUSPENDED
5. Audit log
```

**Note**: This is a **soft suspension**. Historical data (product contributions, requests) is preserved. The connection can potentially be reactivated later.

### Connection Status States

| Status | Description | Can Assign Products? |
|--------|-------------|---------------------|
| `PENDING` | Invitation sent, waiting for supplier response | ❌ No |
| `ACTIVE` | Connection established, data flows freely | ✅ Yes |
| `REJECTED` | Supplier declined the connection | ❌ No |
| `SUSPENDED` | Connection paused (contract ended, etc.) | ❌ No |

### Key Data Relationships

```
TenantConnection (Source of Truth)
├── requester_tenant_id → Tenant (Brand)
├── target_tenant_id → Tenant (Supplier)
└── supplier_profile (1:1 relationship)

SupplierProfile (Denormalized View)
├── tenant_id → Tenant (Brand - owner)
├── connection_id → TenantConnection (FK)
└── supplier_tenant_id → Tenant (Supplier - denormalized)
```

---

## Product/Product Contribution Lifecycle

### Overview

The Product Contribution lifecycle manages the collaborative workflow between Brands and Suppliers to create and maintain technical product data. It involves:
- **Product Identity**: The "shell" (SKU, name, description, media)
- **ProductVersion**: Technical data snapshots (BOM, supply chain, environmental impacts)
- **ProductContributionRequest**: Work orders/tasks tracking the collaboration

### Architecture Pattern

The system uses a **versioning pattern** with:
- **Version Sequence**: Major versions (1, 2, 3...) - new assignments create new sequences
- **Revision**: Minor revisions within a sequence (0, 1, 2...) - created when brand requests changes
- **Status Tracking**: Both Request status and Version status are tracked independently

### Lifecycle Flow

#### Phase 1: Product Creation (Brand)

**Endpoint**: `POST /api/v1/products/`

**Service Method**: `ProductService.create_product()`

**Execution Steps:**

```
1. Validate SKU uniqueness within brand's tenant
2. Create Product Identity:
   - tenant_id = brand.id
   - sku, name, description, identifiers (EAN, UPC, ERP ID)
   - lifecycle_status = PRE_RELEASE (default)
   - pending_version_name = initial_version_name
3. Create initial media files (if provided):
   - Upload base64 images to storage
   - Create ProductMedia records
   - Set main image if specified
4. Audit log
```

**Note**: Product creation does **not** create a ProductVersion. Versions are created when products are assigned to suppliers.

#### Phase 2: Product Assignment to Supplier (Brand)

**Endpoint**: `POST /api/v1/product-contributions/{product_id}/assign`

**Service Method**: `ProductContributionService.assign_product()`

**Prerequisites:**
- Supplier connection must be `ACTIVE`
- No active request on the latest version

**Execution Steps:**

```
1. Validate:
   - Product belongs to brand
   - SupplierProfile belongs to brand
   - Connection is ACTIVE
   - No active request on latest version
2. Analyze existing versions:
   - Query all ProductVersion for this product
   - Order by version_sequence DESC
   - Determine next_sequence = latest_sequence + 1
3. Find "Golden Master" (Latest APPROVED version):
   - Search versions for status = APPROVED
   - If found: Clone it (deep copy with new sequence)
   - If not found: Create fresh empty version
4. Create ProductVersion:
   - product_id = product.id
   - supplier_tenant_id = real_supplier_id
   - version_sequence = next_sequence
   - revision = 0 (reset for new major version)
   - version_name = brand-provided name
   - status = DRAFT
   - Clone data from approved version (if exists):
     * Materials (with lineage_id preserved)
     * Supply chain nodes (with lineage_id preserved)
     * Certificate links (with lineage_id preserved)
5. Create ProductContributionRequest:
   - connection_id = connection.id
   - brand_tenant_id = brand.id
   - supplier_tenant_id = real_supplier_id
   - initial_version_id = version.id
   - current_version_id = version.id
   - due_date = optional deadline
   - request_note = instructions
   - status = SENT
6. Create initial comment (if request_note provided)
7. Audit log
```

**Key Strategy:**
- Always create a **NEW version sequence** (never reuse)
- Source data from **latest APPROVED version** (ensures clean history)
- If no approved version exists, start **FRESH/EMPTY**

**Version Cloning Logic:**
- Preserves `lineage_id` for materials, supply nodes, certificates
- Creates new ProductVersion record
- Links to same SupplierArtifact files (certificates)
- Resets revision to 0

#### Phase 3: Supplier Views Request (Supplier)

**Endpoint**: `GET /api/v1/product-contributions/{request_id}`

**Service Method**: `ProductContributionService.get_request_detail()`

**Response Includes:**
- Request metadata (status, due_date, brand name)
- Product identity (name, SKU, description, images)
- Current draft data (if status allows editing)
- Activity log (comments, status changes)

**Security Logic:**
- If `status = SENT`: Return empty technical data (supplier hasn't accepted yet)
- If `status = IN_PROGRESS` or `CHANGES_REQUESTED`: Return full technical data

#### Phase 4: Supplier Accepts Request (Supplier)

**Endpoint**: `POST /api/v1/product-contributions/{request_id}/action`

**Action**: `{"action": "accept"}`

**Service Method**: `ProductContributionService.handle_workflow_action()`

**Execution Steps:**

```
1. Validate:
   - Request belongs to supplier
   - Request status = SENT
   - Version status = DRAFT or REJECTED
2. Update Request:
   - status = IN_PROGRESS
3. Update Version:
   - status = DRAFT (ensure editable)
4. Add comment (if note provided)
5. Audit log
```

**State Transitions:**
- Request: `SENT` → `IN_PROGRESS`
- Version: `DRAFT` or `REJECTED` → `DRAFT`

#### Phase 5: Supplier Saves Draft Data (Supplier)

**Endpoint**: `PUT /api/v1/product-contributions/{request_id}/data`

**Service Method**: `ProductContributionService.save_draft_data()`

**Prerequisites:**
- Request status = `IN_PROGRESS` or `CHANGES_REQUESTED`
- Version status = `DRAFT`

**Execution Steps:**

```
1. Validate request and version are editable
2. Update scalar fields:
   - manufacturing_country
   - total_carbon_footprint
   - total_energy_mj
   - total_water_usage
3. Replace Materials (full replace strategy):
   - Delete all existing ProductVersionMaterial
   - Create new records from input
   - Preserve lineage_id for existing items
   - Generate new lineage_id for new items
4. Replace Supply Chain (full replace strategy):
   - Delete all existing ProductVersionSupplyNode
   - Create new records from input
   - Preserve lineage_id for existing items
5. Replace Certificates (full replace strategy):
   - Delete all existing ProductVersionCertificate
   - For each certificate input:
     a. If temp_file_id (new upload):
        - Validate file extension
        - Upload file to storage
        - Create SupplierArtifact record
        - Link to new artifact
     b. If file_url (existing file):
        - Use source_artifact_id from library
        - Preserve existing file metadata
     c. Fetch issuer from CertificateDefinition
     d. Create ProductVersionCertificate link
   - Preserve lineage_id for existing certificates
6. Commit changes
```

**Lineage Tracking:**
- `lineage_id` is a UUID that tracks the same logical item across versions
- Used for comparison and change tracking
- Preserved when cloning versions
- New items get new lineage_id

**File Handling:**
- New uploads create `SupplierArtifact` records in supplier's vault
- Certificate links reference artifacts via `source_artifact_id`
- File metadata (name, type, size) is stored in certificate link

#### Phase 6: Supplier Submits Data (Supplier)

**Endpoint**: `POST /api/v1/product-contributions/{request_id}/action`

**Action**: `{"action": "submit"}`

**Service Method**: `ProductContributionService.handle_workflow_action()`

**Execution Steps:**

```
1. Validate:
   - Request status = IN_PROGRESS or CHANGES_REQUESTED
   - Version status = DRAFT
2. LOCK DATA:
   - Request.status = SUBMITTED
   - Version.status = SUBMITTED
3. Add comment (if note provided)
4. Audit log
```

**State Transitions:**
- Request: `IN_PROGRESS` or `CHANGES_REQUESTED` → `SUBMITTED`
- Version: `DRAFT` → `SUBMITTED` (LOCKED - immutable)

**Critical**: Once submitted, the version becomes **immutable**. Supplier cannot edit it.

#### Phase 7: Brand Reviews Submission (Brand)

**Endpoint**: `POST /api/v1/product-contributions/{product_id}/requests/{request_id}/review`

**Service Method**: `ProductContributionService.review_submission()`

**Two Actions:**

**A. Approve:**

```
1. Validate request belongs to brand
2. Update Request:
   - status = COMPLETED
3. Update Version:
   - status = APPROVED
4. Update Product:
   - updated_at = current timestamp
5. Add comment (optional)
6. Audit log
```

**State Transitions:**
- Request: `SUBMITTED` → `COMPLETED`
- Version: `SUBMITTED` → `APPROVED`

**B. Request Changes:**

```
1. Validate request belongs to brand
2. Require comment (mandatory)
3. Update Request:
   - status = CHANGES_REQUESTED
4. Update Version:
   - status = REJECTED (mark old version as rejected)
5. Create NEW Revision:
   - Clone current version
   - version_sequence = same (no change)
   - revision = current_revision + 1
   - status = DRAFT
   - Preserve all lineage_ids
6. Update Request:
   - current_version_id = new_revision.id
7. Add comment (mandatory)
8. Audit log
```

**State Transitions:**
- Request: `SUBMITTED` → `CHANGES_REQUESTED`
- Old Version: `SUBMITTED` → `REJECTED`
- New Revision: Created with `DRAFT` status

**Revision Strategy:**
- Revisions keep the same `version_sequence`
- Increment `revision` number
- Supplier can now edit the new draft revision

#### Phase 8: Supplier Declines Request (Supplier)

**Endpoint**: `POST /api/v1/product-contributions/{request_id}/action`

**Action**: `{"action": "decline"}`

**Service Method**: `ProductContributionService.handle_workflow_action()`

**Execution Steps:**

```
1. Validate:
   - Request status = SENT, IN_PROGRESS, or CHANGES_REQUESTED
   - Cannot decline if SUBMITTED or COMPLETED
2. Update Request:
   - status = DECLINED
3. Update Version:
   - status = REJECTED
4. Add comment (decline reason)
5. Audit log
```

**State Transitions:**
- Request: `SENT`/`IN_PROGRESS`/`CHANGES_REQUESTED` → `DECLINED`
- Version: `DRAFT` → `REJECTED`

#### Phase 9: Brand Cancels Request (Brand)

**Endpoint**: `POST /api/v1/product-contributions/{product_id}/requests/{request_id}/cancel`

**Service Method**: `ProductContributionService.cancel_request()`

**Prerequisites:**
- Request status must NOT be `SUBMITTED`, `COMPLETED`, or `CANCELLED`
- Version status must NOT be `SUBMITTED` or `APPROVED`

**Execution Steps:**

```
1. Validate request belongs to brand
2. Validate request and version are cancellable
3. Update Request:
   - status = CANCELLED
4. Update Version:
   - status = CANCELLED (if DRAFT or REJECTED)
5. Add comment with cancellation reason
6. Audit log
```

**State Transitions:**
- Request: `SENT`/`IN_PROGRESS`/`CHANGES_REQUESTED` → `CANCELLED`
- Version: `DRAFT`/`REJECTED` → `CANCELLED`

### Request Status States

| Status | Description | Who Can Act | Next Actions |
|--------|-------------|-------------|--------------|
| `SENT` | Request sent, waiting for supplier | Supplier | Accept, Decline |
| `IN_PROGRESS` | Supplier accepted, editing data | Supplier | Save Draft, Submit, Decline |
| `SUBMITTED` | Supplier locked data, sent to brand | Brand | Approve, Request Changes |
| `CHANGES_REQUESTED` | Brand requested changes, new revision created | Supplier | Save Draft, Submit |
| `COMPLETED` | Brand approved the data | - | None (terminal) |
| `DECLINED` | Supplier declined the request | - | None (terminal) |
| `CANCELLED` | Brand cancelled the request | - | None (terminal) |

### Version Status States

| Status | Description | Editable? | Visible to Brand? |
|--------|-------------|-----------|-------------------|
| `DRAFT` | Supplier is editing | ✅ Yes | ❌ No |
| `SUBMITTED` | Locked, sent for review | ❌ No | ✅ Yes |
| `APPROVED` | Brand approved, ready for passport | ❌ No | ✅ Yes |
| `REJECTED` | Brand requested changes or supplier declined | ❌ No | ✅ Yes |
| `CANCELLED` | Workflow aborted | ❌ No | ✅ Yes |

### Version & Revision Strategy

**Version Sequence (Major Versions):**
- Incremented when brand assigns product to supplier
- Always creates new sequence number
- Example: v1, v2, v3

**Revision (Minor Versions):**
- Incremented when brand requests changes
- Keeps same sequence number
- Example: v1.0, v1.1, v1.2

**Cloning Logic:**
- When creating new version: Clone from latest APPROVED version
- When creating revision: Clone from current version (even if REJECTED)
- Preserves `lineage_id` for comparison tracking

**Example Flow:**
```
v1.0 (DRAFT) → v1.0 (SUBMITTED) → v1.0 (REJECTED)
                                    ↓
                              v1.1 (DRAFT) → v1.1 (SUBMITTED) → v1.1 (APPROVED)
                                                                      ↓
                                                              v2.0 (DRAFT) [new assignment]
```

### Key Data Relationships

```
Product (Identity)
├── tenant_id → Tenant (Brand)
└── technical_versions → ProductVersion[]

ProductVersion (Technical Data)
├── product_id → Product
├── supplier_tenant_id → Tenant (Supplier)
├── version_sequence (major version)
├── revision (minor version)
├── materials → ProductVersionMaterial[]
├── supply_chain → ProductVersionSupplyNode[]
└── certificates → ProductVersionCertificate[]

ProductContributionRequest (Work Order)
├── connection_id → TenantConnection
├── brand_tenant_id → Tenant (Brand)
├── supplier_tenant_id → Tenant (Supplier)
├── initial_version_id → ProductVersion
└── current_version_id → ProductVersion (tracks active version)
```

---

## Key Data Models

### TenantConnection

**Purpose**: Source of truth for B2B relationship status

**Key Fields:**
- `requester_tenant_id`: Brand who initiated connection
- `target_tenant_id`: Supplier tenant (nullable until registration)
- `type`: RelationshipType (SUPPLIER, RECYCLER, etc.)
- `status`: ConnectionStatus (PENDING, ACTIVE, REJECTED, SUSPENDED)
- `invitation_token`: Secure token for email invites
- `invitation_email`: Email address invited
- `retry_count`: Number of reinvitation attempts
- `request_note`: Optional message from requester

### SupplierProfile

**Purpose**: Denormalized address book entry for fast reads

**Key Fields:**
- `tenant_id`: Brand who owns this entry
- `connection_id`: FK to TenantConnection (1:1)
- `supplier_tenant_id`: Denormalized supplier tenant ID
- `connection_status`: Denormalized connection status
- `slug`: Denormalized supplier slug
- `retry_count`: Denormalized retry count
- `name`, `description`, `location_country`: CRM data
- `contact_name`, `contact_email`: Contact info
- `is_favorite`: UI flag

### Product

**Purpose**: Product identity (shell)

**Key Fields:**
- `tenant_id`: Brand owner
- `sku`: Unique SKU within tenant
- `name`, `description`: Marketing info
- `ean`, `upc`, `internal_erp_id`: Identifiers
- `lifecycle_status`: ProductLifecycleStatus
- `main_image_url`: Cached main image URL
- `pending_version_name`: Name for next version

### ProductVersion

**Purpose**: Technical data snapshot

**Key Fields:**
- `product_id`: FK to Product
- `supplier_tenant_id`: Supplier who provided data
- `version_sequence`: Major version number
- `revision`: Minor revision number
- `version_name`: Display name
- `status`: ProductVersionStatus
- `manufacturing_country`: Where assembled
- `total_carbon_footprint`, `total_energy_mj`, `total_water_usage`: Environmental impacts
- `mass_kg`: Product weight

### ProductContributionRequest

**Purpose**: Work order tracking collaboration

**Key Fields:**
- `connection_id`: FK to TenantConnection
- `brand_tenant_id`: Brand requester
- `supplier_tenant_id`: Supplier assignee
- `initial_version_id`: Version when request created
- `current_version_id`: Active version being edited
- `due_date`: Submission deadline
- `request_note`: Instructions from brand
- `status`: RequestStatus

---

## State Transitions

### Connection Status Transitions

```
PENDING
  ├─→ ACTIVE (supplier accepts)
  ├─→ REJECTED (supplier declines)
  └─→ SUSPENDED (brand disconnects)

ACTIVE
  └─→ SUSPENDED (brand disconnects)

REJECTED
  └─→ PENDING (brand reinvites)
```

### Request Status Transitions

```
SENT
  ├─→ IN_PROGRESS (supplier accepts)
  └─→ DECLINED (supplier declines)

IN_PROGRESS
  ├─→ SUBMITTED (supplier submits)
  └─→ DECLINED (supplier declines)

SUBMITTED
  ├─→ COMPLETED (brand approves)
  └─→ CHANGES_REQUESTED (brand requests changes)

CHANGES_REQUESTED
  ├─→ SUBMITTED (supplier submits revision)
  └─→ DECLINED (supplier declines)

Any state (except SUBMITTED/COMPLETED)
  └─→ CANCELLED (brand cancels)
```

### Version Status Transitions

```
DRAFT
  ├─→ SUBMITTED (supplier submits)
  ├─→ REJECTED (supplier declines)
  └─→ CANCELLED (brand cancels)

SUBMITTED
  ├─→ APPROVED (brand approves)
  └─→ REJECTED (brand requests changes)

REJECTED
  └─→ DRAFT (new revision created, supplier accepts)

APPROVED
  └─→ (terminal state - used as source for next version)

CANCELLED
  └─→ (terminal state)
```

---

## API Endpoints Reference

### Brand/Supplier Connection Endpoints

| Method | Endpoint | Purpose | Actor |
|--------|----------|---------|-------|
| `GET` | `/api/v1/supplier-profiles/` | List address book | Brand |
| `POST` | `/api/v1/supplier-profiles/` | Add supplier (connect/invite) | Brand |
| `PATCH` | `/api/v1/supplier-profiles/{id}` | Update profile | Brand |
| `DELETE` | `/api/v1/supplier-profiles/{id}` | Disconnect supplier | Brand |
| `GET` | `/api/v1/tenant-connections/invitations/{token}` | Verify invite token | Public |
| `POST` | `/api/v1/tenant-connections/requests/{id}/respond` | Accept/decline connection | Supplier |
| `POST` | `/api/v1/tenant-connections/suppliers/{id}/reinvite` | Resend invitation | Brand |
| `GET` | `/api/v1/tenant-connections/directory/suppliers` | Search supplier directory | Brand |

### Product Contribution Endpoints

#### Supplier Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/v1/product-contributions/` | List incoming requests |
| `GET` | `/api/v1/product-contributions/{request_id}` | Get request detail |
| `POST` | `/api/v1/product-contributions/{request_id}/action` | Accept/decline/submit |
| `PUT` | `/api/v1/product-contributions/{request_id}/data` | Save draft data |
| `POST` | `/api/v1/product-contributions/{request_id}/comments` | Add comment |

#### Brand Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/v1/product-contributions/{product_id}/assign` | Assign product to supplier |
| `GET` | `/api/v1/product-contributions/{product_id}/technical-data` | Get latest approved version |
| `GET` | `/api/v1/product-contributions/{product_id}/collaboration-status` | Get workflow status |
| `POST` | `/api/v1/product-contributions/{product_id}/requests/{request_id}/cancel` | Cancel request |
| `POST` | `/api/v1/product-contributions/{product_id}/requests/{request_id}/review` | Approve/request changes |
| `GET` | `/api/v1/product-contributions/{product_id}/requests/{request_id}/compare` | Compare versions |

### Product Management Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/v1/products/` | List products |
| `POST` | `/api/v1/products/` | Create product |
| `GET` | `/api/v1/products/{id}` | Get product details |
| `PATCH` | `/api/v1/products/{id}/identity` | Update product identity |
| `POST` | `/api/v1/products/{id}/media` | Add media |
| `DELETE` | `/api/v1/products/media/{id}` | Delete media |
| `PATCH` | `/api/v1/products/{id}/media/{id}/main` | Set main image |
| `POST` | `/api/v1/products/{id}/media/reorder` | Reorder media |
| `GET` | `/api/v1/products/{id}/versions` | Get version history |

---

## Important Implementation Details

### Denormalization Strategy

The system uses denormalization for performance:
- `SupplierProfile` stores denormalized connection status
- Both tables are updated together during state changes
- `TenantConnection` remains the source of truth

### Lineage Tracking

- `lineage_id` is a UUID that tracks the same logical item across versions
- Used for materials, supply nodes, and certificates
- Enables comparison and change tracking
- Preserved during version cloning

### File Management

- Certificate files are stored as `SupplierArtifact` records
- Certificate links (`ProductVersionCertificate`) reference artifacts
- Files can be reused across versions via `source_artifact_id`
- File metadata (name, type, size) stored in certificate link

### Version Cloning

- Deep cloning preserves all nested data
- Preserves `lineage_id` for comparison
- Links to same artifact files (doesn't duplicate)
- Creates new ProductVersion record with incremented sequence/revision

### Security & Validation

- Brand can only manage their own products/profiles
- Supplier can only access their assigned requests
- Version status guards prevent editing locked data
- Request status guards prevent invalid state transitions
- File extension validation for certificates

### Audit Logging

- All state changes are logged via `_perform_audit_log`
- Logs include tenant_id, user_id, entity_type, entity_id, action, changes
- Background tasks handle async logging

---

## Summary

This system implements a sophisticated B2B collaboration platform with:

1. **Dual-table connection architecture** (TenantConnection + SupplierProfile) for performance and clarity
2. **Versioning system** with major versions and revisions for tracking product data evolution
3. **State machine workflows** ensuring data integrity and preventing invalid transitions
4. **Lineage tracking** for comparing changes across versions
5. **File artifact management** allowing suppliers to maintain a library of reusable certificates
6. **Comprehensive audit logging** for compliance and debugging

The lifecycles are designed to handle complex real-world scenarios including:
- Suppliers declining requests
- Brands requesting changes (creating revisions)
- Cancellations at various stages
- Reinvitations for failed connections
- Multiple versions and revisions per product
