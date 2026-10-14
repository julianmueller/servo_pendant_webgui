// Keyboard jogging: digit keys 1..9 (top row or numpad) jog joint 1..9 while held; with Ctrl (or Shift) negative.
// Escape emits 'stop'. Emits 'jog' {index, value} every 50 ms per held key (heartbeat) and value 0 on release.
// Swallows the keys the page uses plus plain typing, so the browser's find-as-you-type / quick find never opens.
export default {
  template: "<span style='display:none'></span>",
  props: {
    count: { type: Number, default: 7 },
  },
  data() {
    return { held: {}, negative: false, timer: null };
  },
  methods: {
    digit(e) {
      const m = /^(?:Digit|Numpad)([1-9])$/.exec(e.code);
      return m ? Number(m[1]) - 1 : null;
    },
    editable(e) {
      const t = e.target;
      return t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
    },
    sign() {
      return this.negative ? -1 : 1;
    },
    emitAll() {
      for (const idx of Object.keys(this.held)) this.$emit("jog", { index: Number(idx), value: this.sign() });
    },
    onKeyDown(e) {
      if (this.editable(e)) return;
      this.negative = e.ctrlKey || e.shiftKey;
      if (e.code === "Escape") {
        e.preventDefault();
        this.releaseAll();
        this.$emit("stop");
        return;
      }
      const idx = this.digit(e);
      if (idx !== null) {
        e.preventDefault();
        e.stopPropagation();
        if (idx < this.count && !(idx in this.held)) {
          this.held[idx] = true;
          this.emitAll();
          if (!this.timer) this.timer = setInterval(this.emitAll, 50);
        }
        return;
      }
      if (e.key === "Control" || e.key === "Shift") {
        this.emitAll(); // direction changed while a joint key is held
        return;
      }
      // plain typing (and Firefox's quick-find keys / and ') would open the browser's search bar
      if (!e.ctrlKey && !e.altKey && !e.metaKey && (e.key.length === 1 || e.key === "/")) e.preventDefault();
    },
    onKeyUp(e) {
      this.negative = e.ctrlKey || e.shiftKey;
      const idx = this.digit(e);
      if (idx !== null && idx in this.held) {
        e.preventDefault();
        delete this.held[idx];
        this.$emit("jog", { index: idx, value: 0 });
        if (Object.keys(this.held).length === 0) {
          clearInterval(this.timer);
          this.timer = null;
        }
      } else if (e.key === "Control" || e.key === "Shift") {
        this.emitAll();
      }
    },
    releaseAll() {
      for (const idx of Object.keys(this.held)) this.$emit("jog", { index: Number(idx), value: 0 });
      this.held = {};
      clearInterval(this.timer);
      this.timer = null;
    },
    onVisibility() {
      if (document.hidden) this.releaseAll();
    },
  },
  mounted() {
    window.addEventListener("keydown", this.onKeyDown, true);
    window.addEventListener("keyup", this.onKeyUp, true);
    window.addEventListener("blur", this.releaseAll);
    document.addEventListener("visibilitychange", this.onVisibility);
  },
  unmounted() {
    this.releaseAll();
    window.removeEventListener("keydown", this.onKeyDown, true);
    window.removeEventListener("keyup", this.onKeyUp, true);
    window.removeEventListener("blur", this.releaseAll);
    document.removeEventListener("visibilitychange", this.onVisibility);
  },
};
