// Picking of the jog gizmos in the 3D view (robot_view.py): the joint rings and the Cartesian arrows.
// The tubes are a few pixels thin, too thin to hit with a ray, so picking is done in screen space: the gizmo whose
// outline (a polyline in the gizmo's local frame) comes nearest to the pointer, within a few pixels.
// Emits 'pick3d' on the scene element: {type: 'hover', key} when the gizmo under the mouse changes (key null: none)
// and {type: 'press', key} on a click or tap that did not turn the camera.
// Gizmos marked as overlay are drawn over the robot (no depth test), so the rings and arrows behind it stay visible.
window.spScenePick = {
  DRAG_PX: 6, // a press that moved further turned the camera
  TOLERANCE_PX: { mouse: 12, pen: 16, touch: 24 },

  install(sceneId, items, overlayIds, tries = 0) {
    const s = getElement(sceneId);
    if (!s || !s.camera || !s.renderer) {
      if (tries < 50) setTimeout(() => this.install(sceneId, items, overlayIds, tries + 1), 200);
      return;
    }
    s.sp_pick_items = items;
    for (const id of overlayIds) this.overlay(s, id);
    if (s.sp_pick) return;
    s.sp_pick = { key: null, down: null };
    const el = s.$el;
    el.addEventListener("pointerdown", (e) => {
      s.sp_pick.down = { x: e.clientX, y: e.clientY };
    });
    el.addEventListener("pointermove", (e) => {
      if (e.pointerType !== "mouse") return; // no hover on touch screens
      const down = s.sp_pick.down;
      const dragging = down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > this.DRAG_PX;
      this.hover(s, dragging ? null : this.pick(s, e));
    });
    el.addEventListener("pointerup", (e) => {
      const down = s.sp_pick.down;
      s.sp_pick.down = null;
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > this.DRAG_PX) return;
      const key = this.pick(s, e);
      if (key !== null) s.$emit("pick3d", { type: "press", key });
    });
    el.addEventListener("pointercancel", () => (s.sp_pick.down = null));
    el.addEventListener("pointerleave", () => this.hover(s, null));
  },

  hover(s, key) {
    if (key === s.sp_pick.key) return;
    s.sp_pick.key = key;
    s.renderer.domElement.style.cursor = key === null ? "" : "pointer";
    s.$emit("pick3d", { type: "hover", key });
  },

  // The scene's registry holds {mesh, ready_promise} (newer NiceGUI) or the three.js object itself (older)
  mesh(s, id) {
    const object = s.objects.get(id);
    return object?.isObject3D ? object : object?.mesh;
  },

  overlay(s, id, tries = 0) {
    const object = s.objects.get(id);
    if (!object) {
      if (tries < 50) setTimeout(() => this.overlay(s, id, tries + 1), 200); // not created yet
      return;
    }
    Promise.resolve(object.ready_promise)
      .then(() => {
        const mesh = this.mesh(s, id);
        if (!mesh) return;
        mesh.renderOrder = 10;
        for (const m of [].concat(mesh.material || [])) m.depthTest = false;
      })
      .catch(() => {});
  },

  shown(mesh) {
    for (let o = mesh; o; o = o.parent) if (!o.visible) return false;
    return true;
  },

  pick(s, e) {
    const rect = s.renderer.domElement.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    let best = null;
    let bestDistance = this.TOLERANCE_PX[e.pointerType] ?? this.TOLERANCE_PX.mouse;
    for (const item of s.sp_pick_items || []) {
      const mesh = this.mesh(s, item.id);
      if (!mesh || !this.shown(mesh)) continue;
      const v = mesh.position.clone(); // a THREE.Vector3 (THREE itself is not global)
      let previous = null;
      for (const p of item.points) {
        v.set(p[0], p[1], p[2]).applyMatrix4(mesh.matrixWorld).project(s.camera);
        const point = v.z < 1 ? [((v.x + 1) / 2) * rect.width, ((1 - v.y) / 2) * rect.height] : null;
        if (point && previous) {
          const d = this.segmentDistance(px, py, previous, point);
          if (d < bestDistance) [best, bestDistance] = [item.key, d];
        }
        previous = point;
      }
    }
    return best;
  },

  segmentDistance(px, py, [ax, ay], [bx, by]) {
    const dx = bx - ax;
    const dy = by - ay;
    const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy || 1)));
    return Math.hypot(px - ax - t * dx, py - ay - t * dy);
  },
};
