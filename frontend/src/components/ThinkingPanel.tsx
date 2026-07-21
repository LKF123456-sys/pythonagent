// 思考过程折叠面板：流式展示 supervisor/answer 的 <thinking> 内容
import { useEffect, useRef, useState } from "react";
import { IconBrain, IconChevron } from "./icons";

interface Props {
  content: string;
  /** 是否正在流式输出（自动展开 + 跟随滚动） */
  live?: boolean;
}

export function ThinkingPanel({ content, live = false }: Props) {
  // 流式中默认展开，结束后折叠
  const [open, setOpen] = useState(live);
  const bodyRef = useRef<HTMLDivElement>(null);
  const wasLive = useRef(live);

  useEffect(() => {
    if (live && !wasLive.current) setOpen(true);
    if (!live && wasLive.current) setOpen(false);
    wasLive.current = live;
  }, [live]);

  // 流式期间自动滚动到底部
  useEffect(() => {
    if (open && live && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [content, open, live]);

  if (!content) return null;

  return (
    <div className="thinking-panel">
      <button className="thinking-head" onClick={() => setOpen((o) => !o)}>
        <span className={`chev ${open ? "open" : ""}`}>
          <IconChevron style={{ width: 12, height: 12 }} />
        </span>
        <IconBrain style={{ width: 13, height: 13 }} />
        <span>思考过程</span>
        {live && <span className="thinking-live">● 推理中</span>}
      </button>
      {open && (
        <div className="thinking-body" ref={bodyRef}>
          {content}
        </div>
      )}
    </div>
  );
}
