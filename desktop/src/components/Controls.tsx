import type { ReactNode } from "react";
import { ChevronDown, FolderOpen, FolderTree } from "lucide-react";

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

export function Field({ label, hint, children, wide = false, name }: {
  label: string;
  hint?: string;
  children: ReactNode;
  wide?: boolean;
  name?: string;
}) {
  return (
    <label className={`field ${wide ? "field-wide" : ""}`} data-field={name}>
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
  onBrowseFolder,
  name,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
  onBrowse: () => void;
  /** 可选：第二个"选择目录"按钮（文件夹模式素材） */
  onBrowseFolder?: () => void;
  name?: string;
}) {
  return (
    <Field label={label} wide name={name}>
      <span className="path-control">
        <input value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
        <button type="button" className="icon-button" onClick={onBrowse} aria-label={`浏览${label}`} title={`浏览${label}（文件）`}>
          <FolderOpen size={16} aria-hidden="true" />
        </button>
        {onBrowseFolder ? (
          <button type="button" className="icon-button" onClick={onBrowseFolder} aria-label={`选择${label}目录`} title={`选择${label}目录（文件夹模式）`}>
            <FolderTree size={16} aria-hidden="true" />
          </button>
        ) : null}
      </span>
    </Field>
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
