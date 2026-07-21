// 轻量 Toast（无额外依赖，事件总线 + 宿主组件渲染）
import { useEffect, useState } from "react";

export interface ToastItem {
  id: number;
  text: string;
  kind: "info" | "success" | "error";
}

type Listener = (items: ToastItem[]) => void;

let items: ToastItem[] = [];
let listeners: Listener[] = [];
let seq = 0;

function emit(): void {
  listeners.forEach((l) => l(items));
}

export function toast(text: string, kind: ToastItem["kind"] = "info"): void {
  const id = ++seq;
  items = [...items, { id, text, kind }];
  emit();
  window.setTimeout(() => {
    items = items.filter((t) => t.id !== id);
    emit();
  }, 3600);
}

/** Toast 宿主：挂载在应用根部 */
export function ToastHost() {
  const [list, setList] = useState<ToastItem[]>(items);

  useEffect(() => {
    const l: Listener = (next) => setList([...next]);
    listeners.push(l);
    return () => {
      listeners = listeners.filter((x) => x !== l);
    };
  }, []);

  if (list.length === 0) return null;
  return (
    <div className="toast-stack">
      {list.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
}
