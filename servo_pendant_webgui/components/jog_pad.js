// Spring-return jog pad (2D touchpad, or a 1D rocker with axes 'x' / 'y'), sized by CSS.
// Touch anywhere and drag: the drag offset (not the touch position) is the velocity command, so touching never jumps
// to speed. Emits 'jog' {x, y} (-1..1) every 50 ms while touched (heartbeat) and {x: 0, y: 0} on release.
const MARGIN = 30; // px, half the puck size

export default {
  template: `
    <div class="sp-pad" ref="pad" :class="{ 'sp-active': active, 'sp-disabled': disabled, ['sp-pad-' + axes]: true }"
         @pointerdown.prevent="onDown" @pointermove.prevent="onMove" @pointerup="release" @pointercancel="release">
      <div v-if="axes !== 'y'" class="sp-pad-hline"></div>
      <div v-if="axes !== 'x'" class="sp-pad-vline"></div>
      <div v-if="labels.left" class="sp-pad-label sp-left">{{ labels.left }}</div>
      <div v-if="labels.right" class="sp-pad-label sp-right">{{ labels.right }}</div>
      <div v-if="labels.up" class="sp-pad-label sp-up">{{ labels.up }}</div>
      <div v-if="labels.down" class="sp-pad-label sp-down">{{ labels.down }}</div>
      <div class="sp-puck" :style="puckStyle"></div>
    </div>`,
  props: {
    axes: { type: String, default: "xy" },
    labels: { type: Object, default: () => ({}) },
    disabled: { type: Boolean, default: false },
  },
  data() {
    return { x: 0, y: 0, x0: 0, y0: 0, active: false, timer: null };
  },
  computed: {
    puckStyle() {
      return {
        left: `calc(50% + ${this.x} * (50% - ${MARGIN}px))`,
        top: `calc(50% - ${this.y} * (50% - ${MARGIN}px))`,
      };
    },
  },
  methods: {
    onDown(e) {
      if (this.disabled) return;
      e.currentTarget.setPointerCapture(e.pointerId);
      this.x0 = e.clientX;
      this.y0 = e.clientY;
      this.x = 0;
      this.y = 0;
      this.active = true;
      this.emit();
      clearInterval(this.timer);
      this.timer = setInterval(this.emit, 50);
    },
    onMove(e) {
      if (!this.active) return;
      const r = this.$refs.pad.getBoundingClientRect();
      const clamp = (v) => Math.max(-1, Math.min(1, v));
      // the shorter side defines full scale, so the rocker and the pad feel the same
      const half = Math.max(40, Math.min(this.axes === "y" ? r.height : r.width, this.axes === "x" ? r.width : r.height) / 2 - MARGIN);
      this.x = this.axes === "y" ? 0 : clamp((e.clientX - this.x0) / half);
      this.y = this.axes === "x" ? 0 : clamp(-(e.clientY - this.y0) / half);
    },
    release() {
      if (!this.active) return;
      this.active = false;
      clearInterval(this.timer);
      this.timer = null;
      this.$emit("jog", { x: 0, y: 0 });
      this.x = 0;
      this.y = 0; // snap back at once: the release is already sent, nothing may look still active
    },
    emit() {
      const dz = (v) => (Math.abs(v) < 0.05 ? 0 : v); // dead zone around the touch point
      this.$emit("jog", { x: dz(this.x), y: dz(this.y) });
    },
  },
  watch: {
    disabled(v) {
      if (v) this.release();
    },
  },
  mounted() {
    window.addEventListener("blur", this.release);
  },
  unmounted() {
    clearInterval(this.timer);
    window.removeEventListener("blur", this.release);
  },
};
