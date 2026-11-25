const dateFormat = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
});
const timeFormat = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});
const currency = new Intl.NumberFormat("zh-CN", {style: "currency", currency: "CNY"});
const dayMs = 86_400_000;

class HuayuanRechargePoints extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("请指定充值记录实体");
    this.entity = config.entity;
    this.previousRecords = undefined;
    if (!this.shadowRoot) this.attachShadow({mode: "open"});
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        header { display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
        h2 { font: inherit; font-weight: 600; font-size: 1.1rem; margin: 0; }
        select { font: inherit; color: var(--primary-text-color); background: var(--card-background-color);
          border: 1px solid var(--divider-color); border-radius: 8px; padding: 5px 8px; }
        canvas { width: 100%; height: 225px; display: block; margin-top: 12px; touch-action: pan-y; }
        canvas:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
        output { display: block; min-height: 1.5em; margin: 4px 0 0; color: var(--secondary-text-color); }
        details { margin-top: 6px; }
        summary { cursor: pointer; }
        table { width: 100%; border-collapse: collapse; margin-top: 4px; }
        td, th { padding: 5px 0; text-align: left; border-bottom: 1px solid var(--divider-color); }
        td:last-child, th:last-child { text-align: right; }
      </style>
      <ha-card>
        <header><h2>充值记录</h2><select aria-label="交易时间范围">
          <option value="90">最近 90 天</option><option value="365">最近一年</option>
          <option value="all" selected>全部记录</option>
        </select></header>
        <canvas tabindex="0" role="img" aria-label="充值折线图，使用左右方向键选择交易，完整交易也可展开明细查看"></canvas>
        <output aria-live="polite"></output>
        <details><summary>交易明细</summary><table><thead><tr>
          <th>交易时间（北京时间）</th><th>金额</th>
        </tr></thead><tbody></tbody></table></details>
      </ha-card>`;
    this.canvas = this.shadowRoot.querySelector("canvas");
    this.range = this.shadowRoot.querySelector("select");
    this.output = this.shadowRoot.querySelector("output");
    this.summary = this.shadowRoot.querySelector("summary");
    this.table = this.shadowRoot.querySelector("tbody");
    this.range.addEventListener("change", () => this.updatePoints());
    this.canvas.addEventListener("pointermove", (event) => this.pickPoint(event));
    this.canvas.addEventListener("click", (event) => this.pickPoint(event));
    this.canvas.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      if (!this.points.length) return;
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const index = this.selected == null ? this.points.length - 1 : this.selected + direction;
      this.showPoint(Math.max(0, Math.min(this.points.length - 1, index)));
    });
    this.resizeObserver?.disconnect();
    this.resizeObserver = new ResizeObserver(() => this.draw());
    this.resizeObserver.observe(this.canvas);
    this.rows = [];
    this.updatePoints();
  }

  connectedCallback() {
    if (this.canvas) this.resizeObserver.observe(this.canvas);
  }

  disconnectedCallback() {
    this.resizeObserver?.disconnect();
  }

  set hass(hass) {
    if (!this.entity) return;
    const records = hass.states[this.entity]?.attributes.records;
    if (records === this.previousRecords) return;
    this.previousRecords = records;
    this.rows = (Array.isArray(records) ? records : []).flatMap((row) => {
      const time = Date.parse(row.time);
      const amount = Number(row.amount);
      return Number.isFinite(time) && Number.isFinite(amount) ? [{time, amount}] : [];
    }).sort((a, b) => a.time - b.time);
    this.updatePoints();
  }

  updatePoints() {
    const end = Date.now();
    const days = Number(this.range.value);
    this.start = this.range.value === "all"
      ? (this.rows[0]?.time ?? end) - dayMs
      : end - days * dayMs;
    this.end = end;
    this.points = this.rows.filter(({time}) => time >= this.start && time <= end);
    this.selected = null;
    this.summary.textContent = `交易明细（${this.points.length} 笔）`;
    this.table.replaceChildren(...this.points.slice().reverse().map(({time, amount}) => {
      const row = document.createElement("tr");
      row.insertCell().textContent = timeFormat.format(time);
      row.insertCell().textContent = currency.format(amount);
      return row;
    }));
    this.showPoint(null);
  }

  pickPoint(event) {
    const rect = this.canvas.getBoundingClientRect();
    let nearest = null;
    let distance = 18;
    for (const [index, point] of (this.positions ?? []).entries()) {
      const candidate = Math.hypot(point.x - event.clientX + rect.left,
        point.y - event.clientY + rect.top);
      if (candidate < distance) {
        distance = candidate;
        nearest = index;
      }
    }
    if (nearest !== null) this.showPoint(nearest);
  }

  showPoint(index) {
    this.selected = index;
    const point = this.points[index];
    this.output.textContent = point
      ? `${timeFormat.format(point.time)} · ${currency.format(point.amount)}`
      : (this.points.length ? "点击交易点查看时间和金额" : "此时间范围内没有充值记录");
    this.draw();
  }

  draw() {
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    if (!width || !height) return;
    const scale = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(width * scale);
    this.canvas.height = Math.round(height * scale);
    const ctx = this.canvas.getContext("2d");
    ctx.scale(scale, scale);
    const styles = getComputedStyle(this);
    const color = (name, fallback) => styles.getPropertyValue(name).trim() || fallback;
    const left = 54;
    const right = width - 16;
    const top = 12;
    const bottom = height - 28;
    const amounts = this.points.map(({amount}) => amount);
    const low = Math.min(0, ...amounts);
    const high = Math.max(1, ...amounts);
    ctx.font = "11px system-ui";
    ctx.fillStyle = color("--secondary-text-color", "#555");
    ctx.strokeStyle = color("--divider-color", "#ddd");
    for (let tick = 0; tick <= 4; tick++) {
      const y = bottom - (bottom - top) * tick / 4;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(right, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(`¥${(low + (high - low) * tick / 4).toFixed(0)}`, left - 5, y + 4);
    }
    for (let tick = 0; tick < 3; tick++) {
      ctx.textAlign = ["left", "center", "right"][tick];
      ctx.fillText(dateFormat.format(this.start + (this.end - this.start) * tick / 2),
        left + (right - left) * tick / 2, height - 9);
    }
    this.positions = this.points.map(({time, amount}) => ({
      x: left + (right - left) * (time - this.start) / (this.end - this.start),
      y: bottom - (bottom - top) * (amount - low) / (high - low),
    }));
    ctx.fillStyle = color("--primary-color", "#176c94");
    if (this.positions.length > 1) {
      ctx.strokeStyle = ctx.fillStyle;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.beginPath();
      const [first, ...rest] = this.positions;
      ctx.moveTo(first.x, first.y);
      for (const point of rest) ctx.lineTo(point.x, point.y);
      ctx.stroke();
    }
    for (const [index, {x, y}] of this.positions.entries()) {
      ctx.beginPath();
      ctx.arc(x, y, index === this.selected ? 7 : 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  getCardSize() { return 5; }
}

if (!customElements.get("huayuan-recharge-points")) {
  customElements.define("huayuan-recharge-points", HuayuanRechargePoints);
}
