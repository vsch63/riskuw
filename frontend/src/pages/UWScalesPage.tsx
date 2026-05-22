// src/pages/UWScalesPage.tsx
// Drop-in replacement / new tab under System Configuration
// Matches RiskUW dark theme exactly

import { useState, useEffect, useCallback } from "react";

// ── Types ────────────────────────────────────────────────────
interface TrancheDetail {
  id?: string;
  age_from: number;
  age_to: number;
  value: number;
}

interface TrancheParameter {
  id?: string;
  parameter_name: string;
  parameter_type: "RANGE" | "DISCRETE";
  min_value: number | null;
  max_value: number | null;
}

interface Tranche {
  id?: string;
  description: string;
  effective_date: string;
  expiry_date: string;
  parameter_logic: "AND" | "OR";
  parameters: TrancheParameter[];
  details: TrancheDetail[];
}

interface Scale {
  id?: string;
  name: string;
  description: string;
  scale_type: "UW" | "PREMIUM";
  premium_output_type: "RATE_PER_THOUSAND" | "MULTIPLIER" | "";
  is_active: boolean;
  tranche_count?: number;
  tranches?: Tranche[];
}

// ── Constants ────────────────────────────────────────────────
const PARAMETER_OPTIONS = [
  { value: "age",              label: "Age" },
  { value: "gender",           label: "Gender (1=M, 2=F)" },
  { value: "smoker",           label: "Smoker (1=Yes, 0=No)" },
  { value: "bmi",              label: "BMI" },
  { value: "bp_systolic",      label: "BP Systolic" },
  { value: "bp_diastolic",     label: "BP Diastolic" },
  { value: "occupation_class", label: "Occupation Class (1-4)" },
  { value: "policy_term",      label: "Policy Term (years)" },
  { value: "sum_assured",      label: "Sum Assured" },
  { value: "urine_albumin",    label: "Urine Albumin" },
  { value: "family_history",   label: "Family History (1=Yes, 0=No)" },
];

const API = "/uw-scales";
const token = () => localStorage.getItem("access_token") || "";
const hdrs = () => ({
  "Content-Type": "application/json",
  Authorization: `Bearer ${token()}`,
});

// ── Helpers ──────────────────────────────────────────────────
const emptyTranche = (): Tranche => ({
  description: "",
  effective_date: "",
  expiry_date: "",
  parameter_logic: "AND",
  parameters: [],
  details: [],
});

const emptyScale = (): Scale => ({
  name: "",
  description: "",
  scale_type: "UW",
  premium_output_type: "",
  is_active: true,
  tranches: [emptyTranche()],
});

// ── Sub-components ───────────────────────────────────────────

function Badge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    UW: "bg-teal-500/20 text-teal-400 border border-teal-500/30",
    PREMIUM: "bg-amber-500/20 text-amber-400 border border-amber-500/30",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-medium ${colors[type] || "bg-gray-700 text-gray-400"}`}>
      {type}
    </span>
  );
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${active ? "text-teal-400" : "text-gray-500"}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${active ? "bg-teal-400" : "bg-gray-600"}`} />
      {active ? "Active" : "Inactive"}
    </span>
  );
}

// ── Tranche Parameter Row ─────────────────────────────────────
function ParameterRow({
  param, index, onChange, onRemove,
}: {
  param: TrancheParameter;
  index: number;
  onChange: (i: number, p: TrancheParameter) => void;
  onRemove: (i: number) => void;
}) {
  return (
    <div className="grid grid-cols-12 gap-2 items-center">
      <div className="col-span-4">
        <select
          value={param.parameter_name}
          onChange={e => onChange(index, { ...param, parameter_name: e.target.value })}
          className="w-full bg-[#1a1f2e] border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
        >
          <option value="">Select parameter…</option>
          {PARAMETER_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
      <div className="col-span-2">
        <select
          value={param.parameter_type}
          onChange={e => onChange(index, { ...param, parameter_type: e.target.value as "RANGE" | "DISCRETE" })}
          className="w-full bg-[#1a1f2e] border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
        >
          <option value="RANGE">Range</option>
          <option value="DISCRETE">Discrete</option>
        </select>
      </div>
      <div className="col-span-2">
        <input
          type="number"
          placeholder="Min"
          value={param.min_value ?? ""}
          onChange={e => onChange(index, { ...param, min_value: e.target.value === "" ? null : +e.target.value })}
          className="w-full bg-[#1a1f2e] border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
        />
      </div>
      <div className="col-span-2">
        <input
          type="number"
          placeholder="Max"
          value={param.max_value ?? ""}
          onChange={e => onChange(index, { ...param, max_value: e.target.value === "" ? null : +e.target.value })}
          className="w-full bg-[#1a1f2e] border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
        />
      </div>
      <div className="col-span-2 flex justify-end">
        <button
          onClick={() => onRemove(index)}
          className="text-red-400 hover:text-red-300 text-xs px-2 py-1 rounded hover:bg-red-500/10 transition-colors"
        >
          Remove
        </button>
      </div>
    </div>
  );
}

// ── Tranche Detail Row ────────────────────────────────────────
function DetailRow({
  detail, index, valueLabel, onChange, onRemove,
}: {
  detail: TrancheDetail;
  index: number;
  valueLabel: string;
  onChange: (i: number, d: TrancheDetail) => void;
  onRemove: (i: number) => void;
}) {
  return (
    <div className="grid grid-cols-12 gap-2 items-center">
      <div className="col-span-3">
        <input
          type="number"
          placeholder="Age From"
          value={detail.age_from}
          onChange={e => onChange(index, { ...detail, age_from: +e.target.value })}
          className="w-full bg-[#1a1f2e] border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
        />
      </div>
      <div className="col-span-3">
        <input
          type="number"
          placeholder="Age To"
          value={detail.age_to}
          onChange={e => onChange(index, { ...detail, age_to: +e.target.value })}
          className="w-full bg-[#1a1f2e] border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
        />
      </div>
      <div className="col-span-4">
        <input
          type="number"
          step="0.0001"
          placeholder={valueLabel}
          value={detail.value}
          onChange={e => onChange(index, { ...detail, value: +e.target.value })}
          className="w-full bg-[#1a1f2e] border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
        />
      </div>
      <div className="col-span-2 flex justify-end">
        <button
          onClick={() => onRemove(index)}
          className="text-red-400 hover:text-red-300 text-xs px-2 py-1 rounded hover:bg-red-500/10 transition-colors"
        >
          Remove
        </button>
      </div>
    </div>
  );
}

// ── Tranche Editor ────────────────────────────────────────────
function TrancheEditor({
  tranche, index, scaleType, premiumOutputType, onChange, onRemove,
}: {
  tranche: Tranche;
  index: number;
  scaleType: "UW" | "PREMIUM";
  premiumOutputType: string;
  onChange: (i: number, t: Tranche) => void;
  onRemove: (i: number) => void;
}) {
  const valueLabel =
    scaleType === "UW"
      ? "Debit Points"
      : premiumOutputType === "RATE_PER_THOUSAND"
      ? "Rate per ₹1000 SA"
      : "Multiplier";

  const addParam = () =>
    onChange(index, {
      ...tranche,
      parameters: [
        ...tranche.parameters,
        { parameter_name: "", parameter_type: "RANGE", min_value: null, max_value: null },
      ],
    });

  const addDetail = () =>
    onChange(index, {
      ...tranche,
      details: [...tranche.details, { age_from: 0, age_to: 0, value: 0 }],
    });

  const updateParam = (i: number, p: TrancheParameter) => {
    const params = [...tranche.parameters];
    params[i] = p;
    onChange(index, { ...tranche, parameters: params });
  };

  const removeParam = (i: number) => {
    onChange(index, { ...tranche, parameters: tranche.parameters.filter((_, idx) => idx !== i) });
  };

  const updateDetail = (i: number, d: TrancheDetail) => {
    const details = [...tranche.details];
    details[i] = d;
    onChange(index, { ...tranche, details });
  };

  const removeDetail = (i: number) => {
    onChange(index, { ...tranche, details: tranche.details.filter((_, idx) => idx !== i) });
  };

  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden">
      {/* Tranche header */}
      <div className="bg-[#1a1f2e] px-4 py-3 flex items-center justify-between">
        <span className="text-sm font-medium text-teal-400">Tranche {index + 1}</span>
        <button
          onClick={() => onRemove(index)}
          className="text-red-400 hover:text-red-300 text-xs px-2 py-1 rounded hover:bg-red-500/10 transition-colors"
        >
          Remove Tranche
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Basic info */}
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Description</label>
            <input
              value={tranche.description}
              onChange={e => onChange(index, { ...tranche, description: e.target.value })}
              placeholder="e.g. Male Non-Smoker Age 30-40"
              className="w-full bg-[#0f1420] border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Effective Date</label>
            <input
              type="date"
              value={tranche.effective_date}
              onChange={e => onChange(index, { ...tranche, effective_date: e.target.value })}
              className="w-full bg-[#0f1420] border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Expiry Date <span className="text-gray-600">(blank = open)</span></label>
            <input
              type="date"
              value={tranche.expiry_date}
              onChange={e => onChange(index, { ...tranche, expiry_date: e.target.value })}
              className="w-full bg-[#0f1420] border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
            />
          </div>
        </div>

        {/* Parameters */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <label className="text-xs text-gray-400 uppercase tracking-wide">Parameters</label>
              <div className="flex rounded overflow-hidden border border-gray-700">
                {(["AND", "OR"] as const).map(l => (
                  <button
                    key={l}
                    onClick={() => onChange(index, { ...tranche, parameter_logic: l })}
                    className={`px-3 py-1 text-xs font-medium transition-colors ${
                      tranche.parameter_logic === l
                        ? "bg-teal-600 text-white"
                        : "bg-[#1a1f2e] text-gray-400 hover:text-gray-200"
                    }`}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>
            <button
              onClick={addParam}
              className="text-teal-400 hover:text-teal-300 text-xs px-2 py-1 rounded border border-teal-700 hover:border-teal-500 transition-colors"
            >
              + Add Parameter
            </button>
          </div>

          {tranche.parameters.length === 0 ? (
            <p className="text-xs text-gray-600 italic py-2">No parameters yet — click Add Parameter</p>
          ) : (
            <div className="space-y-2">
              {/* Header */}
              <div className="grid grid-cols-12 gap-2 text-xs text-gray-500 uppercase tracking-wide px-0">
                <div className="col-span-4">Parameter</div>
                <div className="col-span-2">Type</div>
                <div className="col-span-2">Min</div>
                <div className="col-span-2">Max</div>
                <div className="col-span-2"></div>
              </div>
              {tranche.parameters.map((p, i) => (
                <ParameterRow
                  key={i}
                  param={p}
                  index={i}
                  onChange={updateParam}
                  onRemove={removeParam}
                />
              ))}
            </div>
          )}
        </div>

        {/* Age-band details */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-gray-400 uppercase tracking-wide">
              Age-band Output Details
            </label>
            <button
              onClick={addDetail}
              className="text-teal-400 hover:text-teal-300 text-xs px-2 py-1 rounded border border-teal-700 hover:border-teal-500 transition-colors"
            >
              + Add Age Band
            </button>
          </div>

          {tranche.details.length === 0 ? (
            <p className="text-xs text-gray-600 italic py-2">No age bands yet — click Add Age Band</p>
          ) : (
            <div className="space-y-2">
              <div className="grid grid-cols-12 gap-2 text-xs text-gray-500 uppercase tracking-wide">
                <div className="col-span-3">Age From</div>
                <div className="col-span-3">Age To</div>
                <div className="col-span-4">{valueLabel}</div>
                <div className="col-span-2"></div>
              </div>
              {tranche.details.map((d, i) => (
                <DetailRow
                  key={i}
                  detail={d}
                  index={i}
                  valueLabel={valueLabel}
                  onChange={updateDetail}
                  onRemove={removeDetail}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Scale Form Modal ──────────────────────────────────────────
function ScaleModal({
  initial,
  onSave,
  onClose,
}: {
  initial: Scale;
  onSave: (s: Scale) => Promise<void>;
  onClose: () => void;
}) {
  const [scale, setScale] = useState<Scale>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const addTranche = () =>
    setScale(s => ({ ...s, tranches: [...(s.tranches || []), emptyTranche()] }));

  const updateTranche = (i: number, t: Tranche) => {
    const tranches = [...(scale.tranches || [])];
    tranches[i] = t;
    setScale(s => ({ ...s, tranches }));
  };

  const removeTranche = (i: number) =>
    setScale(s => ({ ...s, tranches: (s.tranches || []).filter((_, idx) => idx !== i) }));

  const handleSave = async () => {
    setError("");
    if (!scale.name.trim()) { setError("Scale name is required"); return; }
    if (!scale.tranches?.length) { setError("Add at least one tranche"); return; }
    setSaving(true);
    try {
      await onSave(scale);
    } catch (e: any) {
      setError(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 overflow-y-auto py-8">
      <div className="bg-[#131929] border border-gray-700 rounded-xl w-full max-w-4xl mx-4 shadow-2xl">
        {/* Modal header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-lg font-semibold text-gray-100">
            {scale.id ? "Edit Scale" : "Create UW Scale"}
          </h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-xl leading-none">×</button>
        </div>

        <div className="p-6 space-y-6">
          {/* Scale header fields */}
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Scale Name *</label>
              <input
                value={scale.name}
                onChange={e => setScale(s => ({ ...s, name: e.target.value }))}
                placeholder="e.g. Standard Mortality Table 2024"
                className="w-full bg-[#0f1420] border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Description</label>
              <textarea
                value={scale.description}
                onChange={e => setScale(s => ({ ...s, description: e.target.value }))}
                rows={2}
                placeholder="Brief description of this scale…"
                className="w-full bg-[#0f1420] border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-teal-500 resize-none"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Scale Type *</label>
              <select
                value={scale.scale_type}
                onChange={e => setScale(s => ({ ...s, scale_type: e.target.value as "UW" | "PREMIUM", premium_output_type: "" }))}
                className="w-full bg-[#0f1420] border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
              >
                <option value="UW">UW Scale (Debit Points)</option>
                <option value="PREMIUM">Premium Rate Scale</option>
              </select>
            </div>
            {scale.scale_type === "PREMIUM" && (
              <div>
                <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wide">Output Type *</label>
                <select
                  value={scale.premium_output_type}
                  onChange={e => setScale(s => ({ ...s, premium_output_type: e.target.value as any }))}
                  className="w-full bg-[#0f1420] border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-teal-500"
                >
                  <option value="">Select…</option>
                  <option value="RATE_PER_THOUSAND">Rate per ₹1,000 SA</option>
                  <option value="MULTIPLIER">Multiplier</option>
                </select>
              </div>
            )}
            <div className="flex items-center gap-2 mt-4">
              <input
                type="checkbox"
                id="is_active"
                checked={scale.is_active}
                onChange={e => setScale(s => ({ ...s, is_active: e.target.checked }))}
                className="accent-teal-500"
              />
              <label htmlFor="is_active" className="text-sm text-gray-300">Active</label>
            </div>
          </div>

          {/* Tranches */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-gray-200">Tranches</h3>
              <button
                onClick={addTranche}
                className="flex items-center gap-1.5 bg-teal-600 hover:bg-teal-500 text-white text-xs px-3 py-1.5 rounded transition-colors"
              >
                + Add Tranche
              </button>
            </div>
            <div className="space-y-4">
              {(scale.tranches || []).map((t, i) => (
                <TrancheEditor
                  key={i}
                  tranche={t}
                  index={i}
                  scaleType={scale.scale_type}
                  premiumOutputType={scale.premium_output_type}
                  onChange={updateTranche}
                  onRemove={removeTranche}
                />
              ))}
            </div>
          </div>

          {error && (
            <div className="bg-red-900/30 border border-red-700 rounded px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-700">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white text-sm px-5 py-2 rounded transition-colors"
          >
            {saving ? "Saving…" : "Save Scale"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────
export default function UWScalesPage() {
  const [scales, setScales] = useState<Scale[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState<"ALL" | "UW" | "PREMIUM">("ALL");
  const [showModal, setShowModal] = useState(false);
  const [editingScale, setEditingScale] = useState<Scale | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedData, setExpandedData] = useState<Record<string, Scale>>({});
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const showToast = (msg: string, type: "success" | "error" = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const fetchScales = useCallback(async () => {
    setLoading(true);
    try {
      const url = filterType === "ALL" ? API + "/" : `${API}/?scale_type=${filterType}`;
      const res = await fetch(url, { headers: hdrs() });
      if (!res.ok) throw new Error("Failed to load scales");
      setScales(await res.json());
    } catch (e: any) {
      showToast(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [filterType]);

  useEffect(() => { fetchScales(); }, [fetchScales]);

  const handleExpand = async (id: string) => {
    if (expandedId === id) { setExpandedId(null); return; }
    setExpandedId(id);
    if (expandedData[id]) return;
    try {
      const res = await fetch(`${API}/${id}`, { headers: hdrs() });
      const data = await res.json();
      setExpandedData(p => ({ ...p, [id]: data }));
    } catch {}
  };

  const handleCreate = async (scale: Scale) => {
    const res = await fetch(`${API}/`, {
      method: "POST",
      headers: hdrs(),
      body: JSON.stringify({
        ...scale,
        premium_output_type: scale.premium_output_type || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Create failed");
    }
    showToast("Scale created successfully");
    setShowModal(false);
    fetchScales();
  };

  const handleUpdate = async (scale: Scale) => {
    const res = await fetch(`${API}/${scale.id}`, {
      method: "PUT",
      headers: hdrs(),
      body: JSON.stringify({
        ...scale,
        premium_output_type: scale.premium_output_type || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Update failed");
    }
    showToast("Scale updated successfully");
    setShowModal(false);
    setEditingScale(null);
    fetchScales();
    setExpandedData({});
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete scale "${name}"? This cannot be undone.`)) return;
    try {
      const res = await fetch(`${API}/${id}`, { method: "DELETE", headers: hdrs() });
      if (!res.ok) throw new Error("Delete failed");
      showToast("Scale deleted");
      fetchScales();
    } catch (e: any) {
      showToast(e.message, "error");
    }
  };

  const openEdit = async (id: string) => {
    try {
      const res = await fetch(`${API}/${id}`, { headers: hdrs() });
      const data = await res.json();
      setEditingScale(data);
      setShowModal(true);
    } catch {}
  };

  return (
    <div className="space-y-6">
      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium transition-all ${
          toast.type === "success"
            ? "bg-teal-600 text-white"
            : "bg-red-700 text-white"
        }`}>
          {toast.msg}
        </div>
      )}

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-500 mt-0.5">
            Configure UW debit point scales and premium rate scales — attach them to products
          </p>
        </div>
        <button
          onClick={() => { setEditingScale(null); setShowModal(true); }}
          className="flex items-center gap-2 bg-teal-600 hover:bg-teal-500 text-white text-sm px-4 py-2 rounded-lg transition-colors"
        >
          <span className="text-lg leading-none">+</span>
          New Scale
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 bg-[#1a1f2e] rounded-lg p-1 w-fit">
        {(["ALL", "UW", "PREMIUM"] as const).map(t => (
          <button
            key={t}
            onClick={() => setFilterType(t)}
            className={`px-4 py-1.5 text-sm rounded-md transition-colors font-medium ${
              filterType === t
                ? "bg-[#0f1420] text-teal-400 shadow"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {t === "ALL" ? "All Scales" : t === "UW" ? "UW Scales" : "Premium Scales"}
          </button>
        ))}
      </div>

      {/* Scale list */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading scales…</div>
      ) : scales.length === 0 ? (
        <div className="bg-[#131929] border border-gray-700 rounded-xl p-12 text-center">
          <div className="text-4xl mb-3">⚖️</div>
          <p className="text-gray-400 font-medium">No scales configured yet</p>
          <p className="text-gray-600 text-sm mt-1">
            Create your first UW or Premium rate scale to get started
          </p>
          <button
            onClick={() => { setEditingScale(null); setShowModal(true); }}
            className="mt-4 bg-teal-600 hover:bg-teal-500 text-white text-sm px-4 py-2 rounded-lg transition-colors"
          >
            Create Scale
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {scales.map(scale => {
            const id = scale.id!;
            const isExpanded = expandedId === id;
            const detail = expandedData[id];

            return (
              <div key={id} className="bg-[#131929] border border-gray-700 rounded-xl overflow-hidden">
                {/* Scale row */}
                <div className="flex items-center justify-between px-5 py-4">
                  <div className="flex items-center gap-4 min-w-0">
                    <button
                      onClick={() => handleExpand(id)}
                      className="text-gray-500 hover:text-teal-400 transition-colors flex-shrink-0"
                    >
                      <span className={`inline-block transition-transform ${isExpanded ? "rotate-90" : ""}`}>▶</span>
                    </button>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-gray-100">{scale.name}</span>
                        <Badge type={scale.scale_type} />
                        {scale.premium_output_type && (
                          <span className="text-xs text-gray-500">
                            {scale.premium_output_type === "RATE_PER_THOUSAND" ? "Rate/₹1k" : "Multiplier"}
                          </span>
                        )}
                        <StatusDot active={scale.is_active} />
                      </div>
                      {scale.description && (
                        <p className="text-xs text-gray-500 mt-0.5 truncate">{scale.description}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-4 flex-shrink-0 ml-4">
                    <span className="text-xs text-gray-500">
                      {scale.tranche_count ?? 0} {scale.tranche_count === 1 ? "tranche" : "tranches"}
                    </span>
                    <button
                      onClick={() => openEdit(id)}
                      className="text-xs text-teal-400 hover:text-teal-300 px-2 py-1 rounded hover:bg-teal-500/10 transition-colors"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(id, scale.name)}
                      className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded hover:bg-red-500/10 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>

                {/* Expanded tranche view */}
                {isExpanded && (
                  <div className="border-t border-gray-700 px-5 py-4 bg-[#0f1420]">
                    {!detail ? (
                      <div className="text-xs text-gray-500 py-2">Loading…</div>
                    ) : !detail.tranches?.length ? (
                      <div className="text-xs text-gray-600 italic">No tranches defined</div>
                    ) : (
                      <div className="space-y-4">
                        {detail.tranches.map((t, ti) => (
                          <div key={ti} className="border border-gray-700/60 rounded-lg overflow-hidden">
                            <div className="bg-[#1a1f2e] px-4 py-2.5 flex items-center justify-between">
                              <div className="flex items-center gap-3">
                                <span className="text-xs font-medium text-teal-400">T{ti + 1}</span>
                                <span className="text-sm text-gray-200">{t.description}</span>
                                <span className={`text-xs px-1.5 py-0.5 rounded border ${
                                  t.parameter_logic === "AND"
                                    ? "border-blue-700 text-blue-400 bg-blue-500/10"
                                    : "border-purple-700 text-purple-400 bg-purple-500/10"
                                }`}>{t.parameter_logic}</span>
                              </div>
                              <div className="text-xs text-gray-500">
                                {t.effective_date} → {t.expiry_date || "open"}
                              </div>
                            </div>
                            <div className="p-4 grid grid-cols-2 gap-6">
                              {/* Parameters */}
                              <div>
                                <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Parameters</p>
                                {t.parameters.length === 0 ? (
                                  <p className="text-xs text-gray-700 italic">None</p>
                                ) : (
                                  <table className="w-full text-xs">
                                    <thead>
                                      <tr className="text-gray-600">
                                        <th className="text-left pb-1">Param</th>
                                        <th className="text-right pb-1">Min</th>
                                        <th className="text-right pb-1">Max</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {t.parameters.map((p, pi) => (
                                        <tr key={pi} className="border-t border-gray-800">
                                          <td className="py-1 text-gray-300 capitalize">{p.parameter_name.replace(/_/g, " ")}</td>
                                          <td className="py-1 text-right text-gray-400">{p.min_value ?? "—"}</td>
                                          <td className="py-1 text-right text-gray-400">{p.max_value ?? "—"}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                )}
                              </div>
                              {/* Age-band details */}
                              <div>
                                <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Age-band Output</p>
                                {t.details.length === 0 ? (
                                  <p className="text-xs text-gray-700 italic">None</p>
                                ) : (
                                  <table className="w-full text-xs">
                                    <thead>
                                      <tr className="text-gray-600">
                                        <th className="text-left pb-1">Age</th>
                                        <th className="text-right pb-1">Value</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {t.details.map((d, di) => (
                                        <tr key={di} className="border-t border-gray-800">
                                          <td className="py-1 text-gray-300">{d.age_from}–{d.age_to}</td>
                                          <td className="py-1 text-right text-teal-400 font-medium">{d.value}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <ScaleModal
          initial={editingScale || emptyScale()}
          onSave={editingScale ? handleUpdate : handleCreate}
          onClose={() => { setShowModal(false); setEditingScale(null); }}
        />
      )}
    </div>
  );
}
