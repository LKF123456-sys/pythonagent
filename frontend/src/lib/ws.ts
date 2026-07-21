// WebSocket 客户端：自动重连（指数退避）+ 心跳保活 + 中断生成
import { getAccessToken } from "./api";
import type { WSClientMessage, WSServerMessage } from "../types";

export type WSStatus = "connecting" | "open" | "closed" | "reconnecting";

interface ChatSocketOptions {
  sessionId: string;
  onMessage: (msg: WSServerMessage) => void;
  onStatus?: (status: WSStatus) => void;
}

const HEARTBEAT_INTERVAL = 25_000; // 25s 心跳
const MAX_BACKOFF = 15_000;

export class ChatSocket {
  private ws: WebSocket | null = null;
  private sessionId: string;
  private onMessage: (msg: WSServerMessage) => void;
  private onStatus?: (status: WSStatus) => void;
  private heartbeatTimer: number | null = null;
  private reconnectAttempts = 0;
  private manuallyClosed = false;
  private pendingQueue: WSClientMessage[] = [];

  constructor(opts: ChatSocketOptions) {
    this.sessionId = opts.sessionId;
    this.onMessage = opts.onMessage;
    this.onStatus = opts.onStatus;
  }

  connect(): void {
    this.manuallyClosed = false;
    this.onStatus?.("connecting");
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const token = getAccessToken() ?? "";
    const url = `${proto}://${window.location.host}/ws/chat/${this.sessionId}?token=${encodeURIComponent(token)}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.onStatus?.("open");
      this.startHeartbeat();
      // 冲刷重连期间积压的消息
      while (this.pendingQueue.length) {
        const msg = this.pendingQueue.shift()!;
        this.ws?.send(JSON.stringify(msg));
      }
    };

    this.ws.onmessage = (ev) => {
      try {
        this.onMessage(JSON.parse(ev.data) as WSServerMessage);
      } catch {
        // 忽略无法解析的消息
      }
    };

    this.ws.onclose = () => {
      this.stopHeartbeat();
      if (this.manuallyClosed) {
        this.onStatus?.("closed");
        return;
      }
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      // 错误会触发 onclose，由重连逻辑处理
    };
  }

  private scheduleReconnect(): void {
    this.onStatus?.("reconnecting");
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_BACKOFF);
    this.reconnectAttempts += 1;
    window.setTimeout(() => {
      if (!this.manuallyClosed) this.connect();
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      this.send({ type: "ping" });
    }, HEARTBEAT_INTERVAL);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  send(msg: WSClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      // 连接未就绪时暂存（仅聊天消息需要保序）
      if (msg.type === "chat") this.pendingQueue.push(msg);
    }
  }

  /** 切换会话：断开旧连接并以新 session 重连 */
  switchSession(sessionId: string): void {
    this.sessionId = sessionId;
    this.pendingQueue = [];
    this.ws?.close();
    this.connect();
  }

  close(): void {
    this.manuallyClosed = true;
    this.stopHeartbeat();
    this.ws?.close();
    this.ws = null;
  }
}
