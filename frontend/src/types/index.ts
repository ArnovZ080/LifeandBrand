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
  pack_size: number;
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

export interface StockTake {
  id: number;
  location_id: number;
  take_date: string;
  is_finalised: boolean;
  created_by: string | null;
}

export interface VarianceItem {
  item_id: number;
  item_code: string;
  item_name: string;
  opening_stock: number;
  stock_in: number;
  theoretical_usage: number;
  theoretical_closing: number;
  actual_closing: number;
  variance_quantity: number;
  unit_cost: number;
  variance_value: number;
}
