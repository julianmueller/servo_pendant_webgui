// Spring-return velocity slider. Touch anywhere and drag: the drag distance (not the touch position) is the
// command, so touching never jumps to speed. Emits 'jog' {value: -1..1} every 50 ms while touched (heartbeat)
// and {value: 0} on release. `external` shows a command coming from elsewhere (keyboard) when not touched.
// Ticks at 0 and at ±25 / 50 / 75 % of the travel (where the thumb's centre is at that value; with the quadratic
// response that is 6 / 25 / 56 % of the speed).
const MARGIN = 22; // px, half the thumb width
const TICKS = [-0.75, -0.5, -0.25, 0.25, 0.5, 0.75];
const at = (v) => `calc(50% + ${v} * (50% - ${MARGIN}px))`; // where the thumb's centre is at value v

export default {
  template: `
    <div class="sp-slider" ref="track" :class="{ 'sp-active': active || external !== 0, 'sp-disabled': disabled }"
         @pointerdown.prevent="onDown" @pointermove.prevent="onMove" @pointerup="release" @pointercancel="release">
      <div class="sp-slider-rail"></div>
      <div class="sp-slider-fill" :class="shown >= 0 ? 'sp-pos' : 'sp-neg'" :style="fillStyle"></div>
      <div v-for="t in ticks" :key="t" class="sp-slider-tick" :style="{ left: at(t) }"></div>
      <div class="sp-slider-zero"></div>
      <div class="sp-slider-sign sp-minus">&#8722;</div>
      <div class="sp-slider-sign sp-plus">+</div>
      <div class="sp-slider-thumb" :class="shown >= 0 ? 'sp-pos' : 'sp-neg'" :style="thumbStyle"></div>
    </div>`,
  props: {
    disabled: { type: Boolean, default: false },
    external: { type: Number, default: 0 },
  },
  data() {
    return { value: 0, active: false, x0: 0, timer: null, ticks: TICKS };
  },
  computed: {
    shown() {
      return this.active || Math.abs(this.value) > 0.001 ? this.value : this.external;
    },
    thumbStyle() {
      return { left: at(this.shown) };
    },
    fillStyle() {
      const v = this.shown;
      const w = `calc(${Math.abs(v)} * (50% - ${MARGIN}px))`;
      return v >= 0 ? { left: "50%", width: w } : { left: `calc(50% - ${Math.abs(v)} * (50% - ${MARGIN}px))`, width: w };
    },
  },
  methods: {
    at,
    onDown(e) {
      if (this.disabled) return;
      e.currentTarget.setPointerCapture(e.pointerId);
      this.x0 = e.clientX;
      this.value = 0;
      this.active = true;
      this.emit();
      clearInterval(this.timer);
      this.timer = setInterval(this.emit, 50);
    },
    onMove(e) {
      if (!this.active) return;
      const half = this.$refs.track.getBoundingClientRect().width / 2 - MARGIN;
      this.value = Math.max(-1, Math.min(1, (e.clientX - this.x0) / half));
    },
    release() {
      if (!this.active) return;
      this.active = false;
      clearInterval(this.timer);
      this.timer = null;
      this.$emit("jog", { value: 0 });
      this.value = 0; // snap back at once: the release is already sent, nothing may look still active
    },
    emit() {
      this.$emit("jog", { value: Math.abs(this.value) < 0.03 ? 0 : this.value });
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
