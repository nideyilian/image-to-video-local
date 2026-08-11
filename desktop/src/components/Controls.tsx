import type { ReactNode } from "react";
import { ChevronDown, FolderOpen } from "lucide-react";

export function InspectorSection({
  title,
  summary,
  children,
  defaultOpen = false,
}: {
  title: string;
  summary?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="inspector-section" open={defaultOpen}>
      <summary>
        <span>{title}</span>
        <span className="section-summary">{summary}</span>
        <ChevronDown aria-hidden="true" size={15} />
      </summary>
      <div className="section-body">{children}</div>
    </details>
  );
}

export function Field({ label, hint, children, wide = false }: {
  label: string;
  hint?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <label className={`field ${wide ? "field-wide" : ""}`}>
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

export function PathField({
  label,
  value,
  placeholder,
  onChange,
  onBrowse,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
  onBrowse: () => void;
}) {
  return (
    <Field label={label} wide>
      <span className="path-control">
        <input value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
        <button type="button" className="icon-button" onClick={onBrowse} aria-label={`浏览${label}`} title={`浏览${label}`}>
          <FolderOpen size={16} aria-hidden="true" />
        </button>
      </span>
    </Field>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
  disabled = false,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="toggle-control">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span aria-hidden="true" className="toggle-track"><span /></span>
      <span>{label}</span>
    </label>
  );
}

export function PoolEditor({
  label,
  values,
  selected,
  onChange,
}: {
  label: string;
  values: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  const toggle = (value: string) => {
    onChange(selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]);
  };
  return (
    <details className="pool-editor">
      <summary>{label}<span>{selected.length}/{values.length}</span></summary>
      <div className="pool-grid">
        {values.map((value) => (
          <label key={value}>
            <input type="checkbox" checked={selected.includes(value)} onChange={() => toggle(value)} />
            <span>{value}</span>
          </label>
        ))}
      </div>
    </details>
  );
}
