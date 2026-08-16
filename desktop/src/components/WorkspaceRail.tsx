import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import { Check, Copy, Files, FolderInput, Pencil, Plus, Scissors, Trash2, X } from "lucide-react";
import type { JobState, Workspace } from "../types";

type RailClipboard = { mode: "copy" | "cut"; id: string } | null;

type MenuState = { x: number; y: number; id: string } | null;

type DragState = { id: string; targetId: string; before: boolean } | null;

export function WorkspaceRail({
  workspaces,
  jobs,
  activeId,
  clipboard,
  onSelect,
  onAdd,
  onDuplicate,
  onRename,
  onDuplicateId,
  onCut,
  onPaste,
  onRemoveId,
  onReorder,
  onRemove,
}: {
  workspaces: Workspace[];
  jobs: JobState[];
  activeId: string;
  clipboard: RailClipboard;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onDuplicate: () => void;
  onRename: (id: string, name: string) => void;
  onDuplicateId: (id: string) => void;
  onCut: (id: string) => void;
  onPaste: (targetId: string) => void;
  onRemoveId: (id: string) => void;
  onReorder: (dragId: string, targetId: string, position: "before" | "after") => void;
  onRemove: () => void;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [menu, setMenu] = useState<MenuState>(null);
  const [drag, setDrag] = useState<DragState>(null);
  const dragRef = useRef<{ id: string; startX: number; startY: number; curX: number; curY: number; active: boolean } | null>(null);
  const suppressClickRef = useRef(false);
  const itemElsRef = useRef(new Map<string, HTMLElement>());
  const editInputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const beginRename = (workspace: Workspace) => {
    setEditingId(workspace.id);
    setDraft(workspace.name);
  };

  const commitRename = () => {
    if (editingId && draft.trim()) onRename(editingId, draft);
    setEditingId(null);
  };

  const closeMenu = () => setMenu(null);

  useEffect(() => {
    if (!menu) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };
    const onPointerDown = (event: globalThis.PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) closeMenu();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, [menu]);

  const openMenu = (event: ReactMouseEvent<HTMLElement>, id: string) => {
    event.preventDefault();
    event.stopPropagation();
    onSelect(id);
    const width = 172;
    const itemHeight = 30;
    const estimatedHeight = 6 * itemHeight + 8;
    const x = Math.min(event.clientX, window.innerWidth - width - 8);
    const y = Math.min(event.clientY, window.innerHeight - estimatedHeight - 8);
    setMenu({ x, y, id });
  };

  // ---------- 拖拽排序（pointer 实现，不依赖 HTML5 DnD） ----------

  const hitItem = (x: number, y: number): { id: string; before: boolean } | null => {
    for (const [id, element] of itemElsRef.current) {
      if (!element.isConnected) continue;
      const rect = element.getBoundingClientRect();
      if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
        return { id, before: y < rect.top + rect.height / 2 };
      }
    }
    return null;
  };

  const beginItemDrag = (event: ReactPointerEvent<HTMLElement>, id: string) => {
    if (event.button !== 0 || editingId) return;
    if (event.target instanceof HTMLElement && event.target.closest("input, select, a, textarea")) return;
    dragRef.current = { id, startX: event.clientX, startY: event.clientY, curX: event.clientX, curY: event.clientY, active: false };
    const onMove = (moveEvent: globalThis.PointerEvent) => {
      const pending = dragRef.current;
      if (!pending) return;
      pending.curX = moveEvent.clientX;
      pending.curY = moveEvent.clientY;
      if (!pending.active && Math.hypot(moveEvent.clientX - pending.startX, moveEvent.clientY - pending.startY) < 6) return;
      if (!pending.active) {
        pending.active = true;
        suppressClickRef.current = true;
        document.body.classList.add("is-rail-dragging");
      }
      const hit = hitItem(pending.curX, pending.curY);
      setDrag({
        id: pending.id,
        targetId: hit && hit.id !== pending.id ? hit.id : pending.id,
        before: hit ? hit.before : false,
      });
    };
    const onUp = () => {
      const pending = dragRef.current;
      dragRef.current = null;
      document.body.classList.remove("is-rail-dragging");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      setDrag(null);
      if (pending?.active) {
        const hit = hitItem(pending.curX, pending.curY);
        if (hit && hit.id !== pending.id) {
          onReorder(pending.id, hit.id, hit.before ? "before" : "after");
        }
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const menuWorkspace = menu ? workspaces.find((workspace) => workspace.id === menu.id) : undefined;
  const canRemove = workspaces.length > 1;
  const hasClipboard = clipboard !== null;

  return (
    <aside className="workspace-rail" aria-label="工作区">
      <div className="rail-heading">
        <div>
          <span className="rail-kicker">工作区</span>
          <strong>{workspaces.length} 个配置</strong>
        </div>
        <button className="icon-button" type="button" onClick={onAdd} aria-label="新建工作区" title="新建工作区">
          <Plus size={17} aria-hidden="true" />
        </button>
      </div>

      <div className="workspace-list">
        {workspaces.map((workspace, index) => {
          const selected = workspace.id === activeId;
          const firstError = workspace.validationIssues[0]?.message ?? workspace.validationErrors[0] ?? "";
          const state = workspace.validationErrors.length
            ? firstError
            : workspace.imageCount === null
              ? "尚未扫描"
              : `${workspace.imageCount} 张图片`;
          const isEditing = editingId === workspace.id;
          const isCutSource = clipboard?.mode === "cut" && clipboard.id === workspace.id;
          const isDragging = drag?.id === workspace.id;
          const isDropTarget = drag !== null && drag.targetId === workspace.id && !isDragging;
          const className = [
            "workspace-item",
            selected ? "is-selected" : "",
            isEditing ? "is-editing" : "",
            isCutSource ? "is-cut-source" : "",
            isDragging ? "is-dragging" : "",
            isDropTarget ? (drag.before ? "is-drop-before" : "is-drop-after") : "",
          ].filter(Boolean).join(" ");

          const itemContent = (
            <>
              <span className="workspace-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="workspace-copy">
                {isEditing ? (
                  <span className="workspace-name-edit">
                    <input
                      ref={editInputRef}
                      autoFocus
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      onFocus={(event) => event.target.select()}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") commitRename();
                        if (event.key === "Escape") setEditingId(null);
                      }}
                      onBlur={commitRename}
                      aria-label="工作区名称"
                    />
                    <button type="button" className="icon-button" onClick={commitRename} aria-label="确认重命名"><Check size={13} /></button>
                    <button type="button" className="icon-button" onClick={() => setEditingId(null)} aria-label="取消重命名"><X size={13} /></button>
                  </span>
                ) : (
                  <strong title={workspace.name}>{workspace.name}</strong>
                )}
                <small>{workspace.config.resolution_preset} · {workspace.config.fps} fps</small>
                <span className={`workspace-state ${workspace.validationErrors.length ? "is-warning" : ""}`}>
                  {workspace.validationErrors.length ? <FolderInput size={13} /> : <Files size={13} />}
                  {state}
                </span>
              </span>
              {isCutSource ? <span className="cut-mark" aria-label="已剪切，右键其他工作区粘贴" title="已剪切，右键其他工作区粘贴"><Scissors size={13} /></span> : null}
              {workspace.dirty && !isCutSource ? <span className="dirty-mark" aria-label="有未保存更改" title="有未保存更改" /> : null}
            </>
          );

          return isEditing ? (
            <div key={workspace.id} className={className} onDoubleClick={() => beginRename(workspace)}>
              {itemContent}
            </div>
          ) : (
            <button
              type="button"
              key={workspace.id}
              ref={(element) => {
                if (element) itemElsRef.current.set(workspace.id, element);
                else itemElsRef.current.delete(workspace.id);
              }}
              className={className}
              onClick={() => {
                if (suppressClickRef.current) {
                  suppressClickRef.current = false;
                  return;
                }
                onSelect(workspace.id);
              }}
              onDoubleClick={() => beginRename(workspace)}
              onContextMenu={(event) => openMenu(event, workspace.id)}
              onPointerDown={(event) => beginItemDrag(event, workspace.id)}
              aria-current={selected ? "page" : undefined}
            >
              {itemContent}
            </button>
          );
        })}
      </div>

      {drag ? (
        <div className="rail-drag-hint" role="status">
          <Scissors size={12} />
          <span>
            拖拽排序中：将插入到「{(drag.targetId === drag.id ? "当前位置" : workspaces.find((item) => item.id === drag.targetId)?.name ?? "")}」{drag.before ? "之前" : "之后"}
          </span>
        </div>
      ) : null}

      <div className="rail-queue" aria-label="活动队列">
        <div className="rail-queue-heading"><span>活动队列</span><strong>{jobs.filter((job) => ["queued", "running", "paused", "cancelling"].includes(job.status)).length}</strong></div>
        {jobs.filter((job) => ["queued", "running", "paused", "cancelling"].includes(job.status)).slice(0, 3).map((job) => (
          <div className={`rail-job status-${job.status}`} key={job.job_id}>
            <span className="rail-job-signal" />
            <span><strong>{job.workspaceName}</strong><small>{job.status === "running" ? `渲染中 ${job.progress}%` : job.status === "paused" ? "已暂停" : job.status === "cancelling" ? "取消中" : "等待调度"}</small></span>
          </div>
        ))}
        {!jobs.some((job) => ["queued", "running", "paused", "cancelling"].includes(job.status)) ? <p>暂无活动任务</p> : null}
      </div>

      <div className="rail-actions">
        <button type="button" onClick={onDuplicate}><Copy size={15} />复制</button>
        <button type="button" onClick={onRemove} disabled={!canRemove}><Trash2 size={15} />移除</button>
      </div>
      <div className="rail-note">
        每个工作区保存一套独立参数。批量导出会跳过无效配置。
      </div>

      {menu && menuWorkspace ? (
        <div
          ref={menuRef}
          className="workspace-menu"
          style={{ left: menu.x, top: menu.y }}
          role="menu"
          aria-label={`工作区操作：${menuWorkspace.name}`}
          onContextMenu={(event) => event.preventDefault()}
        >
          <div className="workspace-menu-heading">
            <span>{menuWorkspace.name}</span>
            <button type="button" className="icon-button" onClick={closeMenu} aria-label="关闭菜单"><X size={12} /></button>
          </div>
          <button type="button" role="menuitem" onClick={() => { onSelect(menu.id); closeMenu(); }}><Check size={13} />激活</button>
          <button type="button" role="menuitem" onClick={() => { beginRename(menuWorkspace); closeMenu(); }}><Pencil size={13} />重命名</button>
          <button type="button" role="menuitem" onClick={() => { onDuplicateId(menu.id); closeMenu(); }}><Copy size={13} />复制</button>
          <button type="button" role="menuitem" onClick={() => { onCut(menu.id); closeMenu(); }}><Scissors size={13} />剪切</button>
          <button type="button" role="menuitem" disabled={!hasClipboard} onClick={() => { onPaste(menu.id); closeMenu(); }}><FolderInput size={13} />粘贴到此</button>
          <span className="workspace-menu-divider" />
          <button type="button" role="menuitem" className="is-danger" disabled={!canRemove} onClick={() => { onRemoveId(menu.id); closeMenu(); }}><Trash2 size={13} />移除</button>
        </div>
      ) : null}
    </aside>
  );
}
