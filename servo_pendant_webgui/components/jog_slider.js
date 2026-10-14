// Spring-return velocity slider. Touch anywhere and drag: the drag distance (not the touch position) is the
// command, so touching never jumps to speed. Emits 'jog' {value: -1..1} every 50 ms while touched (heartbeat)
// and {value: 0} on release. `external` shows a command coming from elsewhere (keyboard) when not touched.
const MARGIN = 22; // px, half the thumb width

export default {
  template: `
    <div class="sd-slider" ref="track" :class="{ 'sd-active': active || external !== 0, 'sd-disabled': disabled }"
         @pointerdown.prevent="onDown" @pointermove.prevent="onMove" @pointerup="release" @pointercancel="release">
      <div class="sd-slider-rail"></div>
      <div class="sd-slider-fill" :class="shown >= 0 ? 'sd-pos' : 'sd-neg'" :style="fillStyle"></div>
      <div class="sd-slider-zero"></div>
      <div class="sd-slider-sign sd-minus">&#8722;</div>
      <div class="sd-slider-sign sd-plus">+</div>
      <div class="sd-slider-thumb" :class="shown >= 0 ? 'sd-pos' : 'sd-neg'" :style="thumbStyle"></div>
    </div>`,
  props: {
    disabled: { type: Boolean, default: false },
    external: { type: Number, default: 0 },
  },
  data() {
    return { value: 0, active: false, x0: 0, timer: null };
  },
  computed: {
    shown() {
      return this.active || Math.abs(this.value) > 0.001 ? this.value : this.external;
    },
    thumbStyle() {
      return { left: `calc(50% + ${this.shown} * (50% - ${MARGIN}px))` };
    },
    fillStyle() {
      const v = this.shown;
      const w = `calc(${Math.abs(v)} * (50% - ${MARGIN}px))`;
      return v >= 0 ? { left: "50%", width: w } : { left: `calc(50% - ${Math.abs(v)} * (50% - ${MARGIN}px))`, width: w };
    },
  },
  methods: {
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
