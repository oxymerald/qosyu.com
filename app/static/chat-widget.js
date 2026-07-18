// static/chat-widget.js
class QosyuChat {
  constructor(apiBase, currentUserId, token) {
    this.apiBase = apiBase;
    this.currentUserId = currentUserId;
    this.token = token;
    this.ws = null;
    this.currentChatId = null;
    this.messages = [];
    this.hasMore = false;
    this.lastId = null;
    this.initUI();
    this.loadConversations();
  }

  initUI() {
    // создаём все DOM-элементы (аналогично предыдущему, но улучшенный дизайн)
    // полный код — в конце раздела
  }

  async loadConversations() {
    const resp = await fetch(`${this.apiBase}/chat/conversations`, {
      headers: { Authorization: `Bearer ${this.token}` },
    });
    const convs = await resp.json();
    this.renderConversations(convs);
  }

  async openChat(userId, userName) {
    this.currentChatId = userId;
    this.messages = [];
    this.hasMore = false;
    this.lastId = null;
    await this.loadHistory();
    this.connectWebSocket();
    this.renderChatHeader(userName);
    this.renderMessages();
  }

  async loadHistory() {
    let url = `${this.apiBase}/chat/history/${this.currentChatId}?limit=30`;
    if (this.lastId) url += `&before=${this.lastId}`;
    const resp = await fetch(url, {
      headers: { Authorization: `Bearer ${this.token}` },
    });
    const data = await resp.json();
    this.messages = [...data.messages, ...this.messages];
    this.hasMore = data.has_more;
    if (this.messages.length) this.lastId = this.messages[0].id;
    this.renderMessages();
  }

  connectWebSocket() {
    if (this.ws) this.ws.close();
    this.ws = new WebSocket(
      `ws://localhost:8000/chat/ws/${this.currentChatId}?token=${this.token}`,
    );
    this.ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === "message") {
        this.messages.push(data);
        this.renderMessages();
        this.scrollToBottom();
        // если окно не активно — показать браузерное уведомление
        if (document.hidden) {
          new Notification(data.from_name, { body: data.message });
        }
      }
    };
    this.ws.onclose = () => setTimeout(() => this.connectWebSocket(), 3000);
  }

  sendMessage(text) {
    if (!text.trim()) return;
    this.ws.send(JSON.stringify({ message: text }));
  }

  scrollToBottom() {
    /* ... */
  }
  renderMessages() {
    /* рендер списка */
  }
}
