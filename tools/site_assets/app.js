// 全部条目筛选页。零依赖：筛选条件 = 组内任一命中（OR），组间同时满足（AND），再加搜索词。
// 无 JS 时页面照常展示全部条目，只是不能筛。
(function () {
  "use strict";

  var rows = Array.prototype.slice.call(document.querySelectorAll("#rows > li"));
  var q = document.getElementById("q");
  var count = document.getElementById("count");
  var empty = document.getElementById("empty");
  var clear = document.getElementById("clear");

  // data-* 属性名与筛选项的对应：data-scope / data-gain / data-money / data-time / data-will / data-ev
  var ATTR = { 口径: "scope", 收益: "gain", 钱: "money", 时间: "time", 毅力: "will", 证据: "ev" };

  var active = {}; // group -> Set(values)
  Object.keys(ATTR).forEach(function (g) { active[g] = new Set(); });

  function apply() {
    var needle = q.value.trim().toLowerCase();
    var shown = 0;
    rows.forEach(function (r) {
      var ok = true;
      for (var g in active) {
        var set = active[g];
        if (set.size && !set.has(r.dataset[ATTR[g]])) { ok = false; break; }
      }
      if (ok && needle && r.dataset.search.indexOf(needle) === -1) ok = false;
      r.hidden = !ok;
      if (ok) shown++;
    });
    count.textContent = "显示 " + shown + " 条";
    empty.hidden = shown !== 0 || rows.length === 0;
  }

  document.querySelectorAll(".fchip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var g = chip.dataset.group;
      var v = chip.dataset.value;
      var set = active[g];
      if (set.has(v)) { set.delete(v); chip.classList.remove("on"); chip.setAttribute("aria-pressed", "false"); }
      else { set.add(v); chip.classList.add("on"); chip.setAttribute("aria-pressed", "true"); }
      apply();
    });
  });

  q.addEventListener("input", apply);

  clear.addEventListener("click", function () {
    Object.keys(active).forEach(function (g) { active[g].clear(); });
    document.querySelectorAll(".fchip.on").forEach(function (c) {
      c.classList.remove("on");
      c.setAttribute("aria-pressed", "false");
    });
    q.value = "";
    apply();
  });

  apply();
})();
