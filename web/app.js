/* 对外展示站点前端：查询 / 双语 / 渲染 / 验证码登录 / 订阅入口 */
(function () {
  'use strict';

  var DICTS = window.MC_I18N || {};
  var state = {
    lang: 'zh',
    authed: false,
    subscribed: false,
    publicAccess: false,
    data: null,
    dates: [],
    defaultDate: null,
    window: '10y',
    plan: null,
    paddleConfigured: false,
    shareDataUrl: null
  };

  function t(key, vars) {
    var dict = DICTS[state.lang] || DICTS.zh || {};
    var text = Object.prototype.hasOwnProperty.call(dict, key) ? dict[key] : (DICTS.zh[key] || key);
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        text = String(text).split('{' + k + '}').join(String(vars[k]));
      });
    }
    return text;
  }

  function esc(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function applyStaticI18n() {
    document.documentElement.lang = state.lang === 'zh' ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.getAttribute('data-i18n'));
    });
    document.getElementById('nav-lang').textContent = state.lang === 'zh' ? 'EN' : '中';
  }

  function setMsg(id, text, kind) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = text || '';
    el.className = 'modal-msg' + (kind ? ' ' + kind : '');
  }

  function errorText(code) {
    var key = 'err_' + (code || 'unknown');
    var dict = DICTS[state.lang] || {};
    if (Object.prototype.hasOwnProperty.call(dict, key)) return dict[key];
    return t('err_unknown');
  }

  function api(path, options) {
    options = options || {};
    var opts = { method: options.method || 'GET', headers: {}, credentials: 'same-origin' };
    if (options.body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(options.body);
    }
    return fetch(path, opts).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (json) {
        if (!resp.ok) {
          var err = new Error(json.detail || 'request_failed');
          err.code = json.detail || 'unknown';
          err.status = resp.status;
          throw err;
        }
        return json;
      });
    }).catch(function (err) {
      if (err && err.code) throw err;
      var net = new Error('network_error');
      net.code = 'network_error';
      throw net;
    });
  }

  /* ---------- 字段与规则标题 ---------- */
  function field(key) {
    var snap = state.data && state.data.snapshot;
    return (snap && snap.fields && snap.fields[key]) || {};
  }
  function disp(key) {
    var raw = field(key).display || '–';
    if (state.lang !== 'en') return raw;
    return String(raw)
      .replace(/当日/g, 'day')
      .replace(/^黄金\s*/, 'Gold ')
      .replace(/^白银\s*/, 'Silver ')
      .replace(/暂缺（CME 反爬限制）/g, 'N/A (CME restricted)')
      .replace(/暂缺（IBJA 仅保留近期）/g, 'N/A (IBJA recent only)')
      .replace(/待导入 CME PDF/g, 'Drop CME PDF')
      .replace(/^待导入$/, 'Pending PDF')
      .replace(/^暂缺.*$/, 'N/A');
  }
  function num(raw) {
    if (raw === null || raw === undefined) return null;
    var v = parseFloat(String(raw).replace(/[$+,%\s]/g, ''));
    return isNaN(v) ? null : v;
  }
  function dirCls(key) {
    var f = field(key);
    if (f.direction === 'up' || f.direction === 'down') return f.direction;
    var s = String(f.display || '');
    if (s.charAt(0) === '+') return 'up';
    if (s.charAt(0) === '-' || s.charAt(0) === '\u2212') return 'down';
    if (s.indexOf(' +') >= 0) return 'up';
    if (s.indexOf(' -') >= 0) return 'down';
    return '';
  }

  function headlineFor(model, lang) {
    var names = lang === 'zh' ? { gold: '\u9ec4\u91d1', silver: '\u767d\u94f6' } : { gold: 'Gold', silver: 'Silver' };
    function phrase(item) {
      if (item.close === null || item.day === null) return null;
      if (Math.abs(item.day) < 0.05) return names[item.key] + t('flat');
      if (item.close < 100 && item.day < -1) return names[item.key] + (lang === 'zh' ? '' : ' ') + t('below_dollar', { n: Math.ceil(item.close) });
      if (item.close < 100 && item.day > 1) return names[item.key] + (lang === 'zh' ? '' : ' ') + t('above_dollar', { n: Math.floor(item.close) });
      var degree = Math.abs(item.day) < 0.5 ? t('slight') : (Math.abs(item.day) < 2 ? t('notable') : t('large'));
      var direction = item.day > 0 ? t('higher') : t('lower');
      return lang === 'zh'
        ? names[item.key] + degree + direction
        : names[item.key] + ' ' + degree + ' ' + direction;
    }
    var items = [
      { key: 'gold', close: num(model['gold.tvc_close']), day: num(model['gold.day']) },
      { key: 'silver', close: num(model['silver.tvc_close']), day: num(model['silver.day']) }
    ].sort(function (a, b) { return Math.abs(b.day || 0) - Math.abs(a.day || 0); });
    var a = phrase(items[0]), b = phrase(items[1]);
    if (!a || !b) return disp('meta.headline');
    return lang === 'zh' ? a + '\uff0c' + b + '\u3002' : a.charAt(0).toUpperCase() + a.slice(1) + '; ' + b.charAt(0).toLowerCase() + b.slice(1) + '.';
  }

  function formatDateLine(dateStr) {
    if (!dateStr) return '';
    var parts = dateStr.split('-');
    if (state.lang === 'zh') {
      return parts[0] + ' \u5e74 ' + Number(parts[1]) + ' \u6708 ' + Number(parts[2]) + ' \u65e5';
    }
    var months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    return months[Number(parts[1]) - 1] + ' ' + Number(parts[2]) + ', ' + parts[0];
  }
  function weekdayText() {
    var w = (state.data && state.data.weekday) || '';
    if (state.lang === 'zh') {
      var map = { MONDAY: '\u5468\u4e00', TUESDAY: '\u5468\u4e8c', WEDNESDAY: '\u5468\u4e09', THURSDAY: '\u5468\u56db', FRIDAY: '\u5468\u4e94', SATURDAY: '\u5468\u516d', SUNDAY: '\u5468\u65e5' };
      return map[w] || w;
    }
    return w.charAt(0) + w.slice(1).toLowerCase();
  }

  /* ---------- SVG 折线与交互追踪 ---------- */
  var chartRegistry = {};
  var chartSeq = 0;

  function samplePoints(points, max) {
    if (!points || points.length <= max) return points || [];
    var out = [], step = (points.length - 1) / (max - 1);
    for (var i = 0; i < max; i++) out.push(points[Math.round(i * step)]);
    return out;
  }
  function lineChart(points, opts) {
    if (!points || points.length < 2) return '';
    var pts = samplePoints(points, 600);
    var values = pts.map(function (p) { return p.value; });
    var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
    if (opts.current !== undefined && opts.current !== null) { lo = Math.min(lo, opts.current); hi = Math.max(hi, opts.current); }
    var pad = (hi - lo) * 0.12 || 1; lo -= pad; hi += pad;
    // 手机窄屏使用独立坐标系：viewBox 更窄、字号更大，避免整图缩放后文字不可读。
    var compact = window.innerWidth <= 520;
    var vw = compact ? 360 : 700;
    var vh = 156;
    var x0 = compact ? 11 : 14, x1 = vw - (compact ? 11 : 14);
    var y0 = compact ? 24 : 18, y1 = compact ? 116 : 124;
    var fs = compact ? 10.5 : 9.5, labelY = compact ? 143 : 148;
    function X(i) { return x0 + (x1 - x0) * i / (pts.length - 1); }
    function Y(v) { return y1 - (y1 - y0) * (v - lo) / (hi - lo); }
    var path = pts.map(function (p, i) { return (i ? 'L ' : 'M ') + X(i).toFixed(1) + ',' + Y(p.value).toFixed(1); }).join(' ');
    var area = path + ' L ' + x1 + ',' + y1 + ' L ' + x0 + ',' + y1 + ' Z';
    var grid = [0, 0.5, 1].map(function (r) {
      var y = y0 + (y1 - y0) * r;
      return '<line x1="' + x0 + '" y1="' + y.toFixed(1) + '" x2="' + x1 + '" y2="' + y.toFixed(1) + '" stroke="#2A2B30" stroke-width="1" stroke-dasharray="3 4"/>';
    }).join('');
    var current = '';
    if (opts.current !== undefined && opts.current !== null) {
      var cy = Y(opts.current);
      current = '<line x1="' + x0 + '" y1="' + cy.toFixed(1) + '" x2="' + x1 + '" y2="' + cy.toFixed(1) + '" stroke="#E9E9EC" stroke-opacity=".42" stroke-width="1" stroke-dasharray="5 4"/>' +
        '<text x="' + (x0 + 4) + '" y="' + Math.max(compact ? 14 : 11, cy - 6).toFixed(1) + '" fill="#B7B8BD" font-size="' + fs + '">' + esc(t('chart_current_label', { v: Number(opts.current).toFixed(2) })) + '</text>' +
        '<circle cx="' + x1 + '" cy="' + cy.toFixed(1) + '" r="4" fill="' + opts.color + '" stroke="#0E0F11" stroke-width="2"/>';
    }
    // 底部均匀日期刻度（桌面 5 个，手机 3 个），附带短刻度线
    var tickCount = compact ? 3 : 5;
    var usedIdx = {};
    var labels = '';
    for (var k = 0; k < tickCount; k++) {
      var idx = Math.round(k * (pts.length - 1) / (tickCount - 1));
      if (usedIdx[idx]) continue;
      usedIdx[idx] = true;
      var tx = X(idx);
      var anchor = k === 0 ? 'start' : (k === tickCount - 1 ? 'end' : 'middle');
      labels += '<line x1="' + tx.toFixed(1) + '" y1="' + y1 + '" x2="' + tx.toFixed(1) + '" y2="' + (y1 + 5) + '" stroke="#3A3C44" stroke-width="1"/>' +
        '<text x="' + tx.toFixed(1) + '" y="' + labelY + '" fill="#8E9098" font-size="' + fs + '" text-anchor="' + anchor + '">' + esc(pts[idx].label) + '</text>';
    }
    var cid = 'mc-chart-' + (++chartSeq);
    chartRegistry[cid] = {
      pts: pts, x0: x0, x1: x1, y0: y0, y1: y1, lo: lo, hi: hi, vw: vw, vh: vh,
      color: opts.color, valueText: opts.valueText || '', unitPrefix: !!opts.unitPrefix
    };
    var cross = '<g class="chart-cross" style="display:none">' +
      '<line class="cross-v" x1="0" y1="' + y0 + '" x2="0" y2="' + y1 + '" stroke="#E9E9EC" stroke-opacity=".38" stroke-width="1" stroke-dasharray="3 3"/>' +
      '<line class="cross-h" x1="' + x0 + '" y1="0" x2="' + x1 + '" y2="0" stroke="#E9E9EC" stroke-opacity=".22" stroke-width="1" stroke-dasharray="3 3"/>' +
      '<circle class="cross-halo" cx="0" cy="0" r="8" fill="' + opts.color + '" fill-opacity=".22"/>' +
      '<circle class="cross-dot" cx="0" cy="0" r="4" fill="' + opts.color + '" stroke="#0E0F11" stroke-width="2"/>' +
      '</g>';
    return '<div class="chart-box" data-chart-id="' + cid + '">' +
      '<svg class="chart-svg" viewBox="0 0 ' + vw + ' ' + vh + '" role="img" aria-label="' + esc(opts.aria || 'history') + '" xmlns="http://www.w3.org/2000/svg">' +
      '<defs><linearGradient id="' + opts.gradId + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="' + opts.color + '" stop-opacity=".26"/><stop offset="100%" stop-color="' + opts.color + '" stop-opacity="0"/></linearGradient></defs>' +
      grid + '<path d="' + area + '" fill="url(#' + opts.gradId + ')"/><path d="' + path + '" fill="none" stroke="' + opts.color + '" stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"/>' +
      current + labels + cross + '</svg>' +
      '<div class="chart-tip" hidden></div></div>';
  }

  function bindChartTracking(root) {
    if (!root) return;
    root.querySelectorAll('.chart-box').forEach(function (box) {
      var cid = box.getAttribute('data-chart-id');
      var cfg = chartRegistry[cid];
      var svg = box.querySelector('.chart-svg');
      var cross = box.querySelector('.chart-cross');
      var tip = box.querySelector('.chart-tip');
      if (!cfg || !svg || !cross || !tip) return;
      var vLine = cross.querySelector('.cross-v');
      var hLine = cross.querySelector('.cross-h');
      var halo = cross.querySelector('.cross-halo');
      var dot = cross.querySelector('.cross-dot');

      function showAt(clientX) {
        var rect = svg.getBoundingClientRect();
        if (!rect.width) return;
        var svgX = (clientX - rect.left) / rect.width * cfg.vw;
        var ratio = (svgX - cfg.x0) / (cfg.x1 - cfg.x0);
        if (ratio < 0) ratio = 0;
        if (ratio > 1) ratio = 1;
        var idx = Math.round(ratio * (cfg.pts.length - 1));
        var pt = cfg.pts[idx];
        var px = cfg.x0 + (cfg.x1 - cfg.x0) * idx / (cfg.pts.length - 1);
        var py = cfg.y1 - (cfg.y1 - cfg.y0) * (pt.value - cfg.lo) / (cfg.hi - cfg.lo);

        vLine.setAttribute('x1', px.toFixed(1));
        vLine.setAttribute('x2', px.toFixed(1));
        hLine.setAttribute('y1', py.toFixed(1));
        hLine.setAttribute('y2', py.toFixed(1));
        halo.setAttribute('cx', px.toFixed(1));
        halo.setAttribute('cy', py.toFixed(1));
        dot.setAttribute('cx', px.toFixed(1));
        dot.setAttribute('cy', py.toFixed(1));
        cross.style.display = '';

        var valStr = Number(pt.value).toFixed(2);
        var formatted = cfg.valueText
          ? (cfg.unitPrefix ? (esc(cfg.valueText) + ' ' + valStr) : (valStr + ' ' + esc(cfg.valueText)))
          : valStr;
        tip.innerHTML = '<div class="ct-date">' + esc(pt.label) + '</div>' +
          '<div class="ct-val"><i style="background:' + cfg.color + '"></i>' + formatted + '</div>';
        tip.hidden = false;

        var pxCss = px / cfg.vw * rect.width;
        var pyCss = py / cfg.vh * rect.height;
        var tw = tip.offsetWidth || 120;
        var th = tip.offsetHeight || 44;
        var left = pxCss + 12;
        if (left + tw > rect.width - 4) left = pxCss - tw - 12;
        if (left < 4) left = 4;
        var top = pyCss - th - 10;
        if (top < 4) top = pyCss + 12;
        if (top + th > rect.height - 4) top = Math.max(4, rect.height - th - 4);
        tip.style.left = left.toFixed(1) + 'px';
        tip.style.top = top.toFixed(1) + 'px';
      }

      function hide() {
        cross.style.display = 'none';
        tip.hidden = true;
      }

      svg.addEventListener('mousemove', function (e) { showAt(e.clientX); });
      svg.addEventListener('mouseleave', hide);
      svg.addEventListener('touchstart', function (e) {
        if (e.touches && e.touches.length) showAt(e.touches[0].clientX);
      }, { passive: true });
      svg.addEventListener('touchmove', function (e) {
        if (e.touches && e.touches.length) showAt(e.touches[0].clientX);
      }, { passive: true });
      svg.addEventListener('touchend', hide);
    });
  }

  function ratioChartsHtml() {
    var hist = state.data && state.data.ratio_history;
    var heat = state.data && state.data.heatmap;
    if (!hist || !hist.series || !heat) return '';
    var keys = ['1y', '3y', '5y', '10y'];
    return keys.map(function (w) {
      var win = heat.windows && heat.windows[w];
      if (!win) return '';
      var pts = hist.series
        .filter(function (p) { return p.date >= win.start; })
        .map(function (p) { return { label: p.date, value: p.ratio }; });
      return '<div class="ratio-chart" data-window="' + w + '"' + (w === state.window ? '' : ' hidden') + '>' +
        lineChart(pts, { color: '#D4AF37', gradId: 'grad-ratio-' + w, current: heat.current, valueText: state.lang === 'zh' ? '\u91d1\u94f6\u6bd4' : 'ratio', unitPrefix: true, aria: 'Gold/Silver ratio ' + w }) +
        '</div>';
    }).join('');
  }

  function curvePanelHtml(key, titleKey, subKey, footKey, color, gradId) {
    var curve = state.data && state.data.curves && state.data.curves[key];
    if (!curve) return '';
    var st = curve.stats || {};
    var chg = Number(st.change_pct || 0);
    var cls = chg >= 0 ? 'up' : 'down';
    var sign = chg >= 0 ? '+' : '';
    var sub = t(subKey, { first: st.first_label, last: st.last_label, n: st.count });
    var foot = t(footKey, { asof: curve.as_of, ret: (curve.retrieved_at || '').slice(0, 10) });
    return '<section class="panel"><div class="curve-head"><div><div class="ptitle">' + esc(t(titleKey)) + '</div><div class="curve-sub">' + esc(sub) + '</div></div>' +
      '<div class="curve-kpis"><span>' + t('curve_current') + ' <b>' + Number(st.current).toFixed(2) + ' ' + esc(curve.unit || '') + '</b></span>' +
      '<span class="' + cls + '">' + esc(st.period || '') + ' ' + sign + chg.toFixed(2) + '%</span>' +
      '<span>' + t('curve_range') + ' <em>' + Number(st.min).toFixed(2) + ' \u2013 ' + Number(st.max).toFixed(2) + '</em></span></div></div>' +
      lineChart(curve.points, { color: color, gradId: gradId, current: st.current, valueText: curve.unit || '', aria: titleKey }) +
      '<div class="curve-legend"><span><i style="background:' + color + '"></i>' + esc(t(titleKey)) + '</span></div>' +
      '<div class="curve-foot">' + esc(foot) + '</div></section>';
  }

  /* ---------- 报告主体 ---------- */
  function renderReport() {
    var host = document.getElementById('sheet-host');
    if (!state.data) { host.innerHTML = ''; return; }
    chartRegistry = {};
    chartSeq = 0;
    var data = state.data;
    var fields = (data.snapshot && data.snapshot.fields) || {};
    var model = {};
    Object.keys(fields).forEach(function (k) { model[k] = fields[k].value !== undefined ? fields[k].value : fields[k].display; });

    var isReal = (data.snapshot && data.snapshot.mode) === 'REAL';
    var headline = headlineFor(model, state.lang);
    var verify = data.verification;
    var verifyHtml = '';
    if (isReal) {
      verifyHtml = '<div class="verify-strip"><span class="verify-ok">\u2713 ' + esc(t('real_badge')) + '</span>' +
        '<span>' + esc(data.report_date) + ' \u00b7 ' + esc(t('real_verify_meta')) + '</span>' +
        '<span class="verify-cal">' + esc(t('real_verify_cal')) + '</span></div>';
    } else if (verify && verify.checks && verify.checks.close_gold && verify.checks.close_silver) {
      var gd = Number(verify.checks.close_gold.diff_pct).toFixed(2);
      var sd = Number(verify.checks.close_silver.diff_pct).toFixed(2);
      verifyHtml = '<div class="verify-strip"><span class="verify-ok">\u2713 ' + esc(t('verified_badge')) + '</span>' +
        '<span>' + esc(data.report_date) + ' \u00b7 ' + t('gold') + ' ' + gd + '% \u00b7 ' + t('silver') + ' ' + sd + '%</span>' +
        '<span class="verify-cal">TVC vs COMEX</span></div>';
    }

    var calTag = isReal ? t('card_caliber_real') : 'TVC';
    var weekLab = t(isReal ? 'week_real' : 'week_spot');
    var monthLab = t(isReal ? 'month_real' : 'month_tvc');
    var rangeLab = t(isReal ? 'session_range' : 'friday_range');
    var priorLab = t(isReal ? 'prior_close' : 'tvc_prior');
    var yearAgoLab = t(isReal ? 'year_ago_real' : 'year_ago');
    var ozNote = t(isReal ? 'oz_per_oz_real' : 'oz_per_oz');
    var vsLab = t(isReal ? 'vs_comex' : 'vs_tvc');

    var reportMonthIdx = data.report_date ? Number(data.report_date.split('-')[1]) - 1 : 0;
    var enMonths = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    var monthDisp = state.lang === 'zh' ? String(reportMonthIdx + 1) : (enMonths[reportMonthIdx] || 'MTD');

    var vaultNoteText = t('vault_note');
    if (isReal) {
      var vDates = [];
      if (field('vault.comex_registered').as_of) vDates.push('COMEX ' + field('vault.comex_registered').as_of);
      if (field('vault.shfe').as_of) vDates.push((state.lang === 'zh' ? '\u4e0a\u671f\u6240 ' : 'SHFE ') + field('vault.shfe').as_of);
      if (field('vault.sge').as_of) vDates.push((state.lang === 'zh' ? '\u4e0a\u91d1\u6240 ' : 'SGE ') + field('vault.sge').as_of);
      if (field('vault.lbma').as_of) vDates.push('LBMA ' + field('vault.lbma').as_of);
      if (vDates.length) vaultNoteText = t('vault_note_real', { dates: vDates.join(' \u00b7 ') });
    }

    var heat = data.heatmap || {};
    var winKeys = ['1y', '3y', '5y', '10y'];
    var winButtons = winKeys.map(function (w) {
      return '<button type="button" data-window="' + w + '"' + (w === state.window ? ' class="active"' : '') + '>' + esc(t('heat_' + w)) + '</button>';
    }).join('');

    var html = '<div class="sheet" id="sheet">';
    html += '<header><div class="brandrow"><div class="brand"><span class="brandbar"></span><span>' + esc(t('brand_sub')) + '</span></div></div>' +
      '<h1 class="sheet-title">' + (state.lang === 'zh' ? '\u8d35\u91d1\u5c5e\u6536\u76d8\u65e5\u62a5' : 'Precious Metals Close') + '</h1>' +
      '<div class="dateline">' + esc(weekdayText()) + ' <span>/</span> ' + esc(formatDateLine(data.report_date)) + '</div>' +
      '<p class="headline" id="headline" data-generated="rule">' + esc(headline) + '</p><div class="rule"></div></header>';

    html += '<section class="grid3">';
    html += '<div class="card"><div class="eyebrow">' + t('gold') + ' <b>/</b> ' + esc(calTag) + ' <b>\u00b7</b> USD/oz</div>' +
      '<div class="primary-row"><div class="big">' + esc(disp('gold.tvc_close')) + '</div><div class="chg ' + dirCls('gold.change_abs') + '">' + esc(disp('gold.change_abs')) + '</div></div>' +
      '<div class="pcts"><div><span class="lab">' + t('day') + '</span><span class="val ' + dirCls('gold.day') + '">' + esc(disp('gold.day')) + '</span></div>' +
      '<div><span class="lab">' + esc(weekLab) + '</span><span class="val ' + dirCls('gold.week') + '">' + esc(disp('gold.week')) + '</span></div>' +
      '<div><span class="lab">' + esc(monthLab) + '</span><span class="val ' + dirCls('gold.month') + '">' + esc(disp('gold.month')) + '</span></div></div>' +
      '<div class="hr"></div><div class="rangelabel">' + esc(rangeLab) + '</div>' +
      '<div class="rangeline"><span>' + esc(disp('gold.range_low')) + '</span><span>' + esc(disp('gold.range_high')) + '</span></div>' +
      '<div class="prior">' + esc(priorLab) + ' ' + esc(disp('gold.prior_close')) + '</div></div>';

    html += '<div class="card"><div class="eyebrow">' + t('silver') + ' <b>/</b> ' + esc(calTag) + ' <b>\u00b7</b> USD/oz</div>' +
      '<div class="primary-row"><div class="big">' + esc(disp('silver.tvc_close')) + '</div><div class="chg ' + dirCls('silver.change_abs') + '">' + esc(disp('silver.change_abs')) + '</div></div>' +
      '<div class="pcts"><div><span class="lab">' + t('day') + '</span><span class="val ' + dirCls('silver.day') + '">' + esc(disp('silver.day')) + '</span></div>' +
      '<div><span class="lab">' + esc(weekLab) + '</span><span class="val ' + dirCls('silver.week') + '">' + esc(disp('silver.week')) + '</span></div>' +
      '<div><span class="lab">' + esc(monthLab) + '</span><span class="val ' + dirCls('silver.month') + '">' + esc(disp('silver.month')) + '</span></div></div>' +
      '<div class="hr"></div><div class="rangelabel">' + esc(rangeLab) + '</div>' +
      '<div class="rangeline"><span>' + esc(disp('silver.range_low')) + '</span><span>' + esc(disp('silver.range_high')) + '</span></div>' +
      '<div class="prior">' + esc(priorLab) + ' ' + esc(disp('silver.prior_close')) + '</div></div>';

    function ratioLookback(key, days) {
      var v = field(key).display;
      if (v && v !== '–' && v !== '—') return v;
      var hist = data.ratio_history && data.ratio_history.series;
      if (!hist || !hist.length || !data.report_date) return '–';
      var base = new Date(data.report_date + 'T00:00:00Z');
      base.setUTCDate(base.getUTCDate() - days);
      var target = base.toISOString().slice(0, 10);
      var hit = null;
      for (var i = 0; i < hist.length; i++) {
        if (hist[i].date <= target) hit = hist[i];
        else break;
      }
      return hit ? Number(hit.ratio).toFixed(2) : '–';
    }

    html += '<div class="card"><div class="eyebrow">' + t('ratio') + ' <b>/</b> ' + esc(calTag) + '</div>' +
      '<div class="big ratio">' + esc(disp('ratio.value')) + '</div>' +
      '<div class="chg ' + dirCls('ratio.day') + '" style="margin-bottom:14px">' + esc(disp('ratio.day')) + '</div><div class="hr"></div>' +
      '<div class="kv"><span class="k">' + t('month_ago') + '</span><span class="v">' + esc(disp('ratio.month_ago')) + '</span></div>' +
      '<div class="kv"><span class="k">' + t('quarter_ago') + '</span><span class="v">' + esc(ratioLookback('ratio.quarter_ago', 90)) + '</span></div>' +
      '<div class="kv"><span class="k">' + t('half_year_ago') + '</span><span class="v">' + esc(ratioLookback('ratio.half_year_ago', 180)) + '</span></div>' +
      '<div class="kv"><span class="k">' + esc(yearAgoLab) + '</span><span class="v">' + esc(disp('ratio.year_ago')) + '</span></div>' +
      '<div class="subnote">' + esc(ozNote) + '</div></div></section>';

    html += verifyHtml;

    html += '<section class="panel"><div class="heat-head"><div><div class="ptitle">' + esc(t('heat_title')) + '</div><div class="heat-sub">' + esc(t('heat_sub')) + '</div></div>' +
      '<div class="heat-win" id="heat-win">' + winButtons + '</div></div>' +
      '<div class="heat-body"><div><div class="heat-pct" id="heat-pct">\u2014</div>' +
      '<div class="heat-plabel" id="heat-plabel"></div><div class="heat-cur" id="heat-cur"></div></div>' +
      '<div><div class="heat-bar" id="heat-bar"><div class="heat-marker" id="heat-marker"><span class="heat-flag" id="heat-flag"></span></div></div>' +
      '<div class="heat-scale"><span>0</span><span>25</span><span>50</span><span>75</span><span>100 PR</span></div>' +
      '<div class="heat-range" id="heat-range"></div><div class="heat-bandnote">' + esc(t('heat_bandnote')) + '</div></div></div>' +
      '<div class="ratio-chart-block"><div class="ratio-chart-title"><span>' + esc(t('ratio_chart_title')) + '</span><span id="ratio-chart-win"></span></div>' +
      ratioChartsHtml() + '</div>' +
      '<div class="heat-note" id="heat-note"></div></section>';

    html += '<section class="panel"><div class="ptitle">' + esc(t('bench_title')) + '</div><table><thead><tr><th>' + t('local_market') + '</th><th class="num">' + t('usd_per_oz') + '</th><th class="num">' + esc(vsLab) + '</th></tr></thead><tbody>' +
      [['bench.silver_india','silver_india','bench.silver_india_premium'], ['bench.silver_shanghai','silver_shanghai','bench.silver_shanghai_premium'],
       ['bench.gold_india','gold_india','bench.gold_india_premium'], ['bench.gold_shanghai','gold_shanghai','bench.gold_shanghai_premium']]
        .map(function (r) { return '<tr><td class="name">' + esc(t(r[1])) + '</td><td class="num">' + esc(disp(r[0])) + '</td><td class="num ' + dirCls(r[2]) + '">' + esc(disp(r[2])) + '</td></tr>'; }).join('') +
      '</tbody></table><div class="subnote">' + esc(disp('quality.premium_avg_30d')) + '</div></section>';

    html += '<section class="grid2"><div class="card"><div class="ptitle">' + esc(t('vault_title')) + '</div><table><thead><tr><th>' + t('vault_col') + '</th><th class="num">' + t('latest') + '</th><th class="num">' + t('change') + '</th><th class="num">' + t('d30') + '</th></tr></thead><tbody>' +
      [['vault.comex_registered','vault_comex_reg','vault.comex_registered_chg','vault.comex_registered_d30'],
       ['vault.comex_eligible','vault_comex_eligible','vault.comex_eligible_chg','vault.comex_eligible_d30'],
       ['vault.shfe','vault_shfe','vault.shfe_chg',null],
       ['vault.sge','vault_sge',null,null],
       ['vault.lbma','vault_lbma',null,'vault.lbma_d30']]
        .map(function (r) { return '<tr><td class="name">' + esc(t(r[1])) + '</td><td class="num">' + esc(disp(r[0])) + '</td><td class="num ' + (r[2] ? dirCls(r[2]) : '') + '">' + (r[2] ? esc(disp(r[2])) : '\u2013') + '</td><td class="num ' + (r[3] ? dirCls(r[3]) : '') + '">' + (r[3] ? esc(disp(r[3])) : '\u2013') + '</td></tr>'; }).join('') +
      '</tbody></table><div class="subnote">' + esc(vaultNoteText) + '</div></div>';

    html += '<div class="card"><div class="ptitle">' + esc(t('comex_title')) + '</div><div class="comexwrap">' +
      '<div class="col"><div class="comex-big gold">' + esc(disp('comex.oi_to_registered')) + '</div><div class="mlab">' + esc(t('oi_to_reg')) + '</div></div>' +
      '<div class="col"><div class="comex-big light">' + esc(disp('comex.registered_to_oi')) + '</div><div class="mlab">' + esc(t('reg_to_oi')) + '</div></div></div>' +
      '<div class="hr" style="margin-top:14px"></div><div class="comexwrap">' +
      '<div class="col"><div class="sn">' + esc(disp('comex.notices_total')) + '</div><div class="sl">' + esc(t('notices_total', { m: monthDisp })) + '</div></div>' +
      '<div class="col"><div class="sn">' + esc(disp('comex.latest_report')) + '</div><div class="sl">' + esc(t('latest_report')) + '</div></div></div>' +
      '<div class="subnote">' + esc(disp('quality.stress_score').replace(/<br\s*\/?>/g, ' ')) + '</div></div></section>';

    html += curvePanelHtml('vault', 'curve_vault_title', 'curve_vault_sub', 'curve_vault_foot', '#D4AF37', 'grad-vault');
    html += curvePanelHtml('delivery', 'curve_delivery_title', 'curve_delivery_sub', isReal ? 'curve_delivery_foot_real' : 'curve_delivery_foot', '#7FB2D9', 'grad-delivery');

    html += '<section class="panel"><div class="ptitle">' + esc(t('miners_title')) + '</div><div class="miners">' +
      '<div class="mcol"><div class="mt">' + esc(t('gdx')) + '</div><div class="price"><span>' + esc(disp('miners.gdx')) + '</span><span class="d ' + dirCls('miners.gdx_day') + '">' + esc(disp('miners.gdx_day')) + '</span><span class="cmp">' + esc(disp('miners.gold_day')) + '</span></div>' +
      '<div class="r1y">' + esc(t('etf_ratio')) + ' <b class="' + dirCls('miners.gdx_ratio_1y') + '">' + esc(disp('miners.gdx_ratio_1y')) + '</b></div></div>' +
      '<div class="mcol"><div class="mt">' + esc(t('sil')) + '</div><div class="price"><span>' + esc(disp('miners.sil')) + '</span><span class="d ' + dirCls('miners.sil_day') + '">' + esc(disp('miners.sil_day')) + '</span><span class="cmp">' + esc(disp('miners.silver_day')) + '</span></div>' +
      '<div class="r1y">' + esc(t('etf_ratio')) + ' <b class="' + dirCls('miners.sil_ratio_1y') + '">' + esc(disp('miners.sil_ratio_1y')) + '</b></div></div></div></section>';

    var isReal = (state.data.snapshot && state.data.snapshot.mode) === 'REAL';
    var sourcesKey = isReal && t('footer_sources_real') !== 'footer_sources_real' ? 'footer_sources_real' : 'footer_sources_text';
    var statusKey = isReal && t('footer_status_real') !== 'footer_status_real' ? 'footer_status_real' : 'footer_status_text';
    var creditLine = isReal
      ? '<div class="credit-line">' + esc(t('footer_credit')) + ' <a href="https://metalcharts.org" target="_blank" rel="noopener noreferrer">MetalCharts.org</a></div>'
      : '';
    var shareTag = state.publicAccess ? t('share_tag_preview') : t('share_tag_sub');
    html += '<footer class="sources"><strong>' + esc(t('footer_sources')) + '</strong> \u2014 ' + esc(t(sourcesKey)) + '<br>' +
      '<strong>' + esc(t('footer_status')) + '</strong> \u2014 ' + esc(t(statusKey)) + '<br>' +
      '<strong>' + esc(t('footer_caliber')) + '</strong> \u2014 ' + esc(t('footer_caliber_text')) + '<br>' +
      esc(t('footer_disclaimer')) + creditLine + '</footer>' +
      '<div class="share-bar"><div class="share-meta"><span class="share-tag">' + esc(shareTag) + '</span><span>' + esc(data.report_date) + ' · PNG</span></div>' +
      '<button type="button" class="share-btn" id="btn-share-poster">' + esc(t('share_btn')) + '</button></div></div>';

    host.innerHTML = html;
    bindChartTracking(host);
    var shareBtn = document.getElementById('btn-share-poster');
    if (shareBtn) {
      shareBtn.addEventListener('click', function () {
        if (!state.publicAccess && !state.subscribed) {
          window.alert(t('share_sub_only'));
          openModal('login-modal');
          return;
        }
        if (!window.MCShare || !state.data) return;
        shareBtn.disabled = true;
        shareBtn.textContent = t('share_generating');
        setTimeout(function () {
          try {
            var res = window.MCShare.renderPoster(state.data, {
              lang: state.lang,
              window: state.window,
              headline: headline,
              weekdayText: weekdayText(),
              dateText: formatDateLine(state.data.report_date),
              noticesLabel: t('notices_total', { m: monthDisp }),
              ratioQuarter: ratioLookback('ratio.quarter_ago', 90),
              ratioHalfYear: ratioLookback('ratio.half_year_ago', 180),
              t: t,
              disp: disp
            });
            state.shareDataUrl = res.dataUrl;
            document.getElementById('share-img').src = res.dataUrl;
            setMsg('share-msg', '');
            openModal('share-modal');
          } catch (e) {
            window.alert(t('err_unknown'));
          } finally {
            shareBtn.disabled = false;
            shareBtn.textContent = t('share_btn');
          }
        }, 20);
      });
    }
    renderHeat();
  }

  function renderHeat() {
    var heat = state.data && state.data.heatmap;
    if (!heat || !heat.windows) return;
    var w = heat.windows[state.window] || heat.windows['10y'];
    if (!w) return;
    var pct = Number(w.percentile);
    var pctText = pct.toFixed(1);
    var def = heat.definition || {};
    document.getElementById('heat-pct').innerHTML = pctText + '<small>%</small>';
    document.getElementById('heat-plabel').textContent = (state.lang === 'zh' ? '\u767e\u5206\u4f4d\u6392\u540d PR' : 'Percentile rank PR') + pctText;
    document.getElementById('heat-cur').textContent = t('heat_current') + ' ' + Number(heat.current).toFixed(2) + ' \u00b7 ' + t('heat_below', { p: pctText + '%' });
    var clampedPct = Math.max(0, Math.min(100, pct));
    document.getElementById('heat-marker').style.left = clampedPct + '%';
    var flagEl = document.getElementById('heat-flag');
    flagEl.textContent = t('heat_flag', { p: pctText });
    flagEl.style.transform = clampedPct > 82 ? 'translateX(-85%)' : (clampedPct < 18 ? 'translateX(-15%)' : 'translateX(-50%)');
    function f2(v) { return (v === null || v === undefined || isNaN(Number(v))) ? '\u2013' : Number(v).toFixed(2); }
    document.getElementById('heat-range').textContent = t('heat_range', {
      min: f2(w.min), q1: f2(w.p25 !== undefined ? w.p25 : w.q1), med: f2(w.median),
      q3: f2(w.p75 !== undefined ? w.p75 : w.q3), max: f2(w.max)
    });
    document.querySelectorAll('#heat-win button').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-window') === state.window);
    });
    document.querySelectorAll('.ratio-chart').forEach(function (c) {
      c.hidden = c.getAttribute('data-window') !== state.window;
    });
    var hint = document.getElementById('ratio-chart-win');
    if (hint) hint.textContent = t('ratio_chart_hint', { win: t('heat_' + state.window) });
    var isZh = state.lang === 'zh';
    var metric = isZh ? (def.metric || '') : 'Percentile Rank (PR)';
    var formula = isZh ? (def.formula || '') : 'PR = (count below current + 0.5 x ties) / sample size x 100';
    var quartiles = isZh ? (def.quartiles || '') : 'Q1 = 25th, Q2 = median, Q3 = 75th percentile.';
    var isRealHeat = state.data && state.data.snapshot && state.data.snapshot.mode === 'REAL';
    document.getElementById('heat-note').innerHTML =
      t('heat_term') + esc(metric) + ' \u2014 ' + esc(formula) + '<br>' +
      t('heat_pr_note', { p: pctText }) + esc(quartiles) + '<br>' +
      t('heat_sample', { n: w.samples, start: w.start, asof: heat.as_of, src: heat.source }) + '<br>' +
      t('heat_caliber') + esc(isZh ? (heat.caliber || '') : t(isRealHeat ? 'heat_caliber_en_real' : 'heat_caliber_en'));
  }

  /* ---------- 界面状态 ---------- */
  function setAuthed(authed) {
    state.authed = authed;
    document.getElementById('publicArea').hidden = authed || state.publicAccess;
    document.getElementById('lock-panel').hidden = authed || state.publicAccess;
    document.getElementById('nav-login').hidden = authed || state.publicAccess;
    document.getElementById('nav-logout').hidden = !authed || state.publicAccess;
    var navPrice = document.querySelector('a.nav-btn[href="#pricing"]');
    if (navPrice) navPrice.hidden = state.publicAccess;
    document.getElementById('sheet-host').hidden = !authed;
    updateStatus();
  }

  function updateStatus() {
    var el = document.getElementById('query-status');
    if (!state.authed) {
      el.className = 'query-status lock';
      el.textContent = (state.defaultDate ? (state.lang === 'zh' ? '\u9ed8\u8ba4\u67e5\u8be2\u65e5\u671f ' : 'Default date ') + state.defaultDate + ' \u00b7 ' : '') + t('query_locked');
    } else if (state.publicAccess) {
      el.className = 'query-status';
      el.textContent = (state.lang === 'zh' ? '\u5185\u7f51\u5f00\u653e\u6d4b\u8bd5 \u00b7 \u53ef\u67e5\u8be2 ' : 'Open preview \u00b7 ') +
        state.dates.length + (state.lang === 'zh' ? ' \u4efd\u5f52\u6863\u62a5\u544a' : ' archived reports') +
        (state.data ? ' \u00b7 ' + state.data.report_date : '');
    } else {
      el.className = 'query-status';
      el.textContent = (state.lang === 'zh' ? '\u5df2\u767b\u5f55 \u00b7 \u53ef\u67e5\u8be2 ' : 'Signed in \u00b7 ') +
        state.dates.length + (state.lang === 'zh' ? ' \u4efd\u5f52\u6863\u62a5\u544a' : ' archived reports') +
        (state.data ? ' \u00b7 ' + state.data.report_date : '');
    }
  }

  function openModal(id) { document.getElementById(id).classList.add('open'); }
  function closeModal(id) { document.getElementById(id).classList.remove('open'); }

  function loadReport(date) {
    if (!state.authed) { openModal('login-modal'); return; }
    var btn = document.getElementById('query-btn');
    btn.disabled = true; btn.textContent = t('query_loading');
    return api('/api/reports/' + encodeURIComponent(date)).then(function (data) {
      state.data = data;
      document.getElementById('query-date').value = date;
      renderReport();
      updateStatus();
    }).catch(function (err) {
      window.alert(errorText(err.code));
    }).then(function () {
      btn.disabled = false; btn.textContent = t('query_btn');
    });
  }

  function applyLang(lang) {
    state.lang = lang;
    try { localStorage.setItem('mc_lang', lang); } catch (e) { /* ignore */ }
    applyStaticI18n();
    if (state.plan) document.getElementById('plan-price').textContent = (lang === 'en' ? state.plan_en.price : state.plan.price);
    if (state.authed) renderReport();
    updateStatus();
  }

  function boot() {
    try { state.lang = localStorage.getItem('mc_lang') === 'en' ? 'en' : 'zh'; } catch (e) { /* ignore */ }
    applyStaticI18n();
    document.querySelectorAll('.modal-backdrop').forEach(function (bd) {
      bd.addEventListener('click', function (e) { if (e.target === bd) closeModal(bd.id); });
    });

    api('/api/public/status').then(function (s) {
      state.defaultDate = s.default_date;
      state.plan = s.plan; state.plan_en = s.plan_en;
      state.paddleConfigured = s.paddle_configured;
      state.publicAccess = !!s.public_access;
      if (state.publicAccess) {
        var navPrice = document.querySelector('a.nav-btn[href="#pricing"]');
        if (navPrice) navPrice.hidden = true;
        document.getElementById('nav-login').hidden = true;
        document.getElementById('nav-logout').hidden = true;
      }
      var input = document.getElementById('query-date');
      if (s.default_date) { input.value = s.default_date; input.max = s.default_date; }
      document.getElementById('plan-price').textContent = (state.lang === 'en' ? s.plan_en.price : s.plan.price);
      if (!s.paddle_configured) {
        document.getElementById('btn-subscribe').textContent = t('subscribe_pending');
        document.getElementById('btn-subscribe').disabled = true;
        document.getElementById('subscribe-desc').textContent = t('price_pending');
        document.getElementById('btn-checkout').disabled = true;
      }
      updateStatus();
    }).catch(function (err) { window.alert(errorText(err.code)); });

    api('/api/me').then(function (me) {
      if (me.public_access) state.publicAccess = true;
      state.subscribed = !!me.subscribed;
      if (!me.subscribed) throw new Error('no_active_subscription');
      setAuthed(true);
      return api('/api/reports/dates');
    }).then(function (r) {
      if (!r) return;
      state.dates = r.dates || [];
      state.defaultDate = r.default || state.defaultDate;
      var input = document.getElementById('query-date');
      input.value = state.defaultDate;
      if (state.dates.length) { input.min = state.dates[state.dates.length - 1]; input.max = state.dates[0]; }
      updateStatus();
      return loadReport(state.defaultDate);
    }).catch(function () { setAuthed(false); });

    document.getElementById('query-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var date = document.getElementById('query-date').value;
      if (!date) return;
      loadReport(date);
    });
    document.getElementById('query-latest').addEventListener('click', function () {
      if (state.defaultDate) loadReport(state.defaultDate);
    });
    document.getElementById('nav-lang').addEventListener('click', function () {
      applyLang(state.lang === 'zh' ? 'en' : 'zh');
    });
    [document.getElementById('nav-login'), document.getElementById('lock-login')].forEach(function (b) {
      b.addEventListener('click', function () { setMsg('login-msg', ''); openModal('login-modal'); });
    });
    document.getElementById('login-cancel').addEventListener('click', function () { closeModal('login-modal'); });
    document.getElementById('btn-subscribe').addEventListener('click', function () { openModal('subscribe-modal'); });
    document.getElementById('subscribe-cancel').addEventListener('click', function () { closeModal('subscribe-modal'); });
    document.getElementById('share-close').addEventListener('click', function () { closeModal('share-modal'); });
    document.getElementById('share-download').addEventListener('click', function () {
      if (!state.shareDataUrl || !state.data) return;
      var a = document.createElement('a');
      a.href = state.shareDataUrl;
      a.download = 'metals-close-' + state.data.report_date + '.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    });
    document.getElementById('share-native').addEventListener('click', function () {
      if (!state.shareDataUrl || !state.data) return;
      var fname = 'metals-close-' + state.data.report_date + '.png';
      fetch(state.shareDataUrl).then(function (r) { return r.blob(); }).then(function (blob) {
        var file = new File([blob], fname, { type: 'image/png' });
        if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
          return navigator.share({ files: [file], title: 'Metals Close ' + state.data.report_date });
        }
        if (navigator.clipboard && window.ClipboardItem) {
          return navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]).then(function () {
            setMsg('share-msg', t('share_copied'), 'ok');
          });
        }
        setMsg('share-msg', t('share_fallback_tip'), '');
      }).catch(function () {
        setMsg('share-msg', t('share_fallback_tip'), '');
      });
    });

    document.getElementById('nav-logout').addEventListener('click', function () {
      api('/api/auth/logout', { method: 'POST' }).then(function () {
        state.data = null; state.subscribed = false; document.getElementById('sheet-host').innerHTML = '';
        setAuthed(false);
      }).catch(function (err) { window.alert(errorText(err.code)); });
    });

    document.getElementById('btn-send-code').addEventListener('click', function () {
      var email = document.getElementById('login-email').value.trim();
      if (!email) { setMsg('login-msg', errorText('invalid_email'), 'error'); return; }
      var btn = this; btn.disabled = true;
      api('/api/auth/code', { method: 'POST', body: { email: email, lang: state.lang } }).then(function (r) {
        setMsg('login-msg', r.dev_code ? t('login_dev') + r.dev_code : t('login_sent'), r.dev_code ? 'ok' : 'ok');
        if (r.dev_code) {
          var dev = document.getElementById('dev-code');
          dev.hidden = false; dev.textContent = r.dev_code;
          document.getElementById('login-code').value = r.dev_code;
        }
      }).catch(function (err) { setMsg('login-msg', errorText(err.code), 'error'); })
        .then(function () { btn.disabled = false; });
    });

    document.getElementById('btn-verify').addEventListener('click', function () {
      var email = document.getElementById('login-email').value.trim();
      var code = document.getElementById('login-code').value.trim();
      if (!email || !code) { setMsg('login-msg', errorText('code_invalid'), 'error'); return; }
      var btn = this; btn.disabled = true;
      api('/api/auth/verify', { method: 'POST', body: { email: email, code: code } }).then(function () {
        closeModal('login-modal');
        state.subscribed = true;
        setAuthed(true);
        return api('/api/reports/dates').then(function (r) {
          state.dates = r.dates || []; state.defaultDate = r.default || state.defaultDate;
          var input = document.getElementById('query-date');
          input.value = state.defaultDate;
          if (state.dates.length) { input.min = state.dates[state.dates.length - 1]; input.max = state.dates[0]; }
          return loadReport(state.defaultDate);
        });
      }).catch(function (err) { setMsg('login-msg', errorText(err.code), 'error'); })
        .then(function () { btn.disabled = false; });
    });

    document.getElementById('btn-checkout').addEventListener('click', function () {
      var email = document.getElementById('subscribe-email').value.trim();
      if (!email) { setMsg('subscribe-msg', errorText('invalid_email'), 'error'); return; }
      var btn = this; btn.disabled = true;
      api('/api/subscribe/checkout', { method: 'POST', body: { email: email, lang: state.lang, plan: 'yearly' } })
        .then(function (r) {
          if (r.configured && r.checkout_url) window.location.href = r.checkout_url;
          else setMsg('subscribe-msg', t('price_pending'), 'error');
        })
        .catch(function (err) { setMsg('subscribe-msg', errorText(err.code), 'error'); })
        .then(function () { btn.disabled = false; });
    });

    document.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('#heat-win button');
      if (!b) return;
      state.window = b.getAttribute('data-window');
      renderHeat();
    });

    try {
      var params = new URLSearchParams(window.location.search);
      var w = params.get('w');
      if (w && ['1y','3y','5y','10y'].indexOf(w) >= 0) state.window = w;
      if (params.get('subscribed') === '1') setMsg('login-msg', t('login_sent'), 'ok');
    } catch (e) { /* ignore */ }

    // 手机/桌面断点切换时重绘图表坐标系，保证文字始终可读。
    var lastCompact = window.innerWidth <= 520;
    window.addEventListener('resize', function () {
      var compact = window.innerWidth <= 520;
      if (compact !== lastCompact) {
        lastCompact = compact;
        if (state.data) renderReport();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
