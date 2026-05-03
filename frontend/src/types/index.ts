export type Department = "bar" | "kitchen" | "floor" | "general";
export type BatchStatus = "active" | "expiring_soon" | "expired" | "depleted";

export interface Supplier {
  id: number;
  name: string;
  code: string;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  payment_terms_days: number;
  is_active: boolean;
}

export interface Item {
  id: number;
  code: string;
  name: string;
  category: string;
  department: Department;
  pack_size: number;
  unit_cost: number | null;
  is_perishable: boolean;
  default_shelf_life_days: number | null;
  reorder_level: number | null;
  is_active: boolean;
}

export interface PurchaseOrder {
  id: number;
  po_number: string;
  supplier_id: number;
  location_id: number;
  status: "draft" | "sent" | "partially_received" | "received" | "cancelled";
  order_date: string;
  expected_delivery_date: string | null;
  lines: POLine[];
}

export interface POLine {
  id: number;
  item_id: number;
  quantity_ordered: number;
  unit_price: number;
  quantity_received: number;
}

export interface Delivery {
  id: number;
  grn_number: string;
  supplier_id: number;
  location_id: number;
  delivery_date: string;
  status: "pending" | "verified" | "discrepancy" | "accepted";
  received_by: string | null;
}

export interface ItemBatch {
  id: number;
  item_id: number;
  item_name: string;
  item_code: string;
  location_id: number;
  batch_reference: string | null;
  received_date: string;
  best_before_date: string | null;
  shelf_life_days: number | null;
  days_until_expiry: number | null;
  quantity_received: number;
  quantity_remaining: number;
  unit_cost: number | null;
  status: BatchStatus;
}

export interface SpotCheckBatchCount {
  id: number;
  batch_id: number;
  batch_reference: string | null;
  received_date: string | null;
  best_before_date: string | null;
  days_until_expiry: number | null;
  expected_quantity: number | null;
  actual_quantity: number | null;
  counted_by: string | null;
  counted_at: string | null;
  variance_quantity: number | null;
  notes: string | null;
}

export interface SpotCheckItem {
  id: number;
  item_id: number;
  item_code: string;
  item_name: string;
  item_category: string;
  department: Department;
  unit_abbreviation: string;
  unit_cost: number | null;
  is_perishable: boolean;
  is_overdue: boolean;
  theoretical_quantity: number | null;
  actual_quantity: number | null;
  counted_by: string | null;
  counted_at: string | null;
  variance_quantity: number | null;
  variance_value: number | null;
  variance_pct: number | null;
  days_since_last_check: number | null;
  notes: string | null;
  batch_counts: SpotCheckBatchCount[];
}

export interface SpotCheckSession {
  id: number;
  location_id: number;
  department: Department;
  session_date: string;
  session_slot: number;
  status: "pending" | "partial" | "complete" | "missed";
  assigned_to: string | null;
  overdue_count: number;
  items: SpotCheckItem[];
}

export interface ExtractedInvoiceLine {
  description: string;
  quantity: number;
  unit: string | null;
  unit_price: number;
  line_total: number;
}

export interface InvoiceExtraction {
  supplier_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  subtotal: number | null;
  tax_amount: number | null;
  total_amount: number | null;
  currency: string;
  lines: ExtractedInvoiceLine[];
  confidence: "high" | "medium" | "low";
  extraction_notes: string | null;
}
