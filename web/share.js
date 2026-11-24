/* 竖版日报分享长图生成器（纯 Canvas，零外部依赖，输出 2x 高清 PNG） */
(function () {
  'use strict';

  var FONT_SANS = 'Inter,"Helvetica Neue",Arial,"PingFang SC","Microsoft YaHei",sans-serif';
  var FONT_SERIF = '"Songti SC","SimSun","Noto Serif CJK SC",Georgia,serif';
  var C = {
    bg: '#0E0F11',
    panel: '#16171A',
    line: '#2A2B30',
    lineSoft: '#232429',
    gold: '#D4AF37',
    goldDim: '#8A7330',
    ink: '#E9E9EC',
    sub: '#C9CAD0',
    muted: '#8E9098',
    faint: '#6E7076',
    up: '#4ADE80',
    down: '#F87171',
    blue: '#7FB2D9'
  };

  function rr(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function fillCard(ctx, x, y, w, h, r) {
    rr(ctx, x, y, w, h, r || 10);
    ctx.fillStyle = C.panel;
    ctx.fill();
    ctx.strokeStyle = C.line;
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  function wrapLines(ctx, text, maxW) {
    var str = String(text || '');
    if (!str) return [];
    var lines = [];
    var line = '';
    for (var i = 0; i < str.length; i++) {
      var ch = str[i];
      if (ch === '\n') {
        lines.push(line);
        line = '';
        continue;
      }
      var test = line + ch;
      if (ctx.measureText(test).width > maxW && line) {
        lines.push(line);
        line = ch === ' ' ? '' : ch;
      } else {
        line = test;
      }
    }
    if (line) lines.push(line);
    return lines;
  }

  function drawWrapped(ctx, text, x, y, maxW, lineH, color, font) {
    if (font) ctx.font = font;
    if (color) ctx.fillStyle = color;
    var lines = wrapLines(ctx, text, maxW);
    for (var i = 0; i < lines.length; i++) {
      ctx.fillText(lines[i], x, y + i * lineH);
    }
    return y + lines.length * lineH;
  }

  function dirColor(field) {
    if (!field) return C.ink;
    if (field.direction === 'up') return C.up;
    if (field.direction === 'down') return C.down;
    var s = String(field.display || '');
    if (s.charAt(0) === '+') return C.up;
    if (s.charAt(0) === '-' || s.charAt(0) === '\u2212') return C.down;
    return C.ink;
  }

  function drawSectionTitle(ctx, title, x, y) {
    ctx.fillStyle = C.goldDim;
    ctx.fillRect(x, y - 11, 2.5, 14);
    ctx.font = '600 14px ' + FONT_SANS;
    ctx.fillStyle = C.ink;
    ctx.fillText(title, x + 10, y + 1);
  }

  function sample(pts, max) {
    if (!pts || pts.length <= max) return pts || [];
    var out = [], step = (pts.length - 1) / (max - 1);
    for (var i = 0; i < max; i++) out.push(pts[Math.round(i * step)]);
    return out;
  }

  function drawLineChart(ctx, x, y, w, h, points, color, currentVal) {
    if (!points || points.length < 2) return;
    var pts = sample(points, 300);
    var vals = pts.map(function (p) { return p.value; });
    var lo = Math.min.apply(null, vals);
    var hi = Math.max.apply(null, vals);
    if (currentVal !== undefined && currentVal !== null) {
      lo = Math.min(lo, currentVal);
      hi = Math.max(hi, currentVal);
    }
    var pad = (hi - lo) * 0.12 || 1;
    lo -= pad; hi += pad;
    var x0 = x + 6, x1 = x + w - 6;
    var y0 = y + 10, y1 = y + h - 22;
    function X(i) { return x0 + (x1 - x0) * i / (pts.length - 1); }
    function Y(v) { return y1 - (y1 - y0) * (v - lo) / (hi - lo); }

    ctx.save();
    ctx.strokeStyle = C.line;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 4]);
    [0, 0.5, 1].forEach(function (r) {
      var gy = y0 + (y1 - y0) * r;
      ctx.beginPath();
      ctx.moveTo(x0, gy);
      ctx.lineTo(x1, gy);
      ctx.stroke();
    });
    ctx.setLineDash([]);

    // 渐变填充
    var grad = ctx.createLinearGradient(0, y0, 0, y1);
    grad.addColorStop(0, color + '44');
    grad.addColorStop(1, color + '00');
    ctx.beginPath();
    pts.forEach(function (p, i) {
      if (i === 0) ctx.moveTo(X(i), Y(p.value));
      else ctx.lineTo(X(i), Y(p.value));
    });
    ctx.lineTo(x1, y1);
    ctx.lineTo(x0, y1);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // 折线
    ctx.beginPath();
    pts.forEach(function (p, i) {
      if (i === 0) ctx.moveTo(X(i), Y(p.value));
      else ctx.lineTo(X(i), Y(p.value));
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.8;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // 当前虚线
    if (currentVal !== undefined && currentVal !== null) {
      var cy = Y(currentVal);
      ctx.strokeStyle = 'rgba(233,233,236,0.42)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x0, cy);
      ctx.lineTo(x1, cy);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(x1, cy, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = C.bg;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // 底部 3 个日期刻度
    ctx.font = '400 10px ' + FONT_SANS;
    ctx.fillStyle = C.muted;
    var idxs = [0, Math.floor((pts.length - 1) / 2), pts.length - 1];
    idxs.forEach(function (idx, k) {
      var tx = X(idx);
      ctx.textAlign = k === 0 ? 'left' : (k === 2 ? 'right' : 'center');
      ctx.fillText(pts[idx].label, tx, y + h - 5);
    });
    ctx.textAlign = 'left';
    ctx.restore();
  }

  function renderPoster(data, opts) {
    opts = opts || {};
    var lang = opts.lang === 'en' ? 'en' : 'zh';
    var winKey = opts.window || '10y';
    var headline = opts.headline || '';
    var t = opts.t || function (k) { return k; };
    var disp = opts.disp || function (k) {
      var f = (data.snapshot && data.snapshot.fields && data.snapshot.fields[k]) || {};
      return f.display || '–';
    };
    var field = function (k) {
      return (data.snapshot && data.snapshot.fields && data.snapshot.fields[k]) || {};
    };
    var isReal = (data.snapshot && data.snapshot.mode) === 'REAL';
    var calTag = isReal ? t('card_caliber_real') : 'TVC';

    var W = 800;
    var MAX_H = 3000;
    var DPR = 2;
    var PAD = 34;
    var IW = W - PAD * 2;

    var canvas = document.createElement('canvas');
    canvas.width = W * DPR;
    canvas.height = MAX_H * DPR;
    var ctx = canvas.getContext('2d');
    ctx.scale(DPR, DPR);
    ctx.textBaseline = 'alphabetic';

    // 背景
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, MAX_H);

    var y = 34;

    // 1. 顶部品牌与标题
    ctx.fillStyle = C.gold;
    ctx.fillRect(PAD, y, 3.5, 18);
    ctx.font = '600 12px ' + FONT_SANS;
    ctx.fillStyle = C.gold;
    ctx.fillText('METALS CLOSE  ·  ' + t('brand_sub'), PAD + 12, y + 13);
    y += 48;

    ctx.font = '400 34px ' + FONT_SERIF;
    ctx.fillStyle = C.ink;
    ctx.fillText(lang === 'zh' ? '贵金属收盘日报' : 'Precious Metals Close', PAD, y);
    y += 24;

    ctx.font = '600 12px ' + FONT_SANS;
    ctx.fillStyle = C.gold;
    ctx.fillText((opts.weekdayText || '') + '  /  ' + (opts.dateText || data.report_date || ''), PAD, y);
    y += 24;

    y = drawWrapped(ctx, headline, PAD, y, IW, 22, C.sub, '400 14px ' + FONT_SANS);
    y += 6;
    ctx.strokeStyle = C.goldDim;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD, y);
    ctx.lineTo(W - PAD, y);
    ctx.stroke();
    y += 16;

    // 2. 三列主行情卡片（黄金 / 白银 / 金银比）
    var gap = 12;
    var cw = (IW - gap * 2) / 3;
    var ch = 224;
    var weekLab = t(isReal ? 'week_real' : 'week_spot');
    var monthLab = t(isReal ? 'month_real' : 'month_tvc');
    var rangeLab = t(isReal ? 'session_range' : 'friday_range');
    var priorLab = t(isReal ? 'prior_close' : 'tvc_prior');
    var yearAgoLab = t(isReal ? 'year_ago_real' : 'year_ago');

    function drawMetalCard(idx, titleKey, prefix) {
      var cx = PAD + idx * (cw + gap);
      fillCard(ctx, cx, y, cw, ch);
      ctx.font = '600 10.5px ' + FONT_SANS;
      ctx.fillStyle = C.muted;
      ctx.fillText(t(titleKey) + ' / ' + calTag + ' · USD/oz', cx + 14, y + 24);

      ctx.font = '300 24px ' + FONT_SANS;
      ctx.fillStyle = C.ink;
      ctx.fillText(disp(prefix + '.tvc_close'), cx + 14, y + 58);

      ctx.font = '600 12px ' + FONT_SANS;
      ctx.fillStyle = dirColor(field(prefix + '.change_abs'));
      ctx.fillText(disp(prefix + '.change_abs'), cx + 14, y + 78);

      // 当日 / 1周 / 1月 三列
      var py = y + 104;
      var cols = [
        [t('day'), prefix + '.day'],
        [weekLab, prefix + '.week'],
        [monthLab, prefix + '.month']
      ];
      cols.forEach(function (item, j) {
        var bx = cx + 14 + j * ((cw - 28) / 3);
        ctx.font = '400 9.5px ' + FONT_SANS;
        ctx.fillStyle = C.faint;
        ctx.fillText(item[0], bx, py);
        ctx.font = '600 11.5px ' + FONT_SANS;
        ctx.fillStyle = dirColor(field(item[1]));
        ctx.fillText(disp(item[1]), bx, py + 16);
      });

      ctx.strokeStyle = C.line;
      ctx.beginPath();
      ctx.moveTo(cx + 14, y + 136);
      ctx.lineTo(cx + cw - 14, y + 136);
      ctx.stroke();

      ctx.font = '400 10px ' + FONT_SANS;
      ctx.fillStyle = C.faint;
      ctx.fillText(rangeLab, cx + 14, y + 156);

      ctx.font = '400 11.5px ' + FONT_SANS;
      ctx.fillStyle = C.muted;
      ctx.fillText(disp(prefix + '.range_low'), cx + 14, y + 176);
      ctx.textAlign = 'right';
      ctx.fillText(disp(prefix + '.range_high'), cx + cw - 14, y + 176);
      ctx.textAlign = 'left';

      ctx.font = '400 10.5px ' + FONT_SANS;
      ctx.fillStyle = C.faint;
      ctx.fillText(priorLab + ' ' + disp(prefix + '.prior_close'), cx + 14, y + 204);
    }

    drawMetalCard(0, 'gold', 'gold');
    drawMetalCard(1, 'silver', 'silver');

    // 金银比卡片（含 1个月 / 1季度 / 半年 / 1年）
    var rx = PAD + 2 * (cw + gap);
    fillCard(ctx, rx, y, cw, ch);
    ctx.font = '600 10.5px ' + FONT_SANS;
    ctx.fillStyle = C.muted;
    ctx.fillText(t('ratio') + ' / ' + calTag, rx + 14, y + 24);

    ctx.font = '300 28px ' + FONT_SANS;
    ctx.fillStyle = C.ink;
    ctx.fillText(disp('ratio.value'), rx + 14, y + 60);

    ctx.font = '600 12px ' + FONT_SANS;
    ctx.fillStyle = dirColor(field('ratio.day'));
    ctx.fillText(disp('ratio.day'), rx + 14, y + 80);

    ctx.strokeStyle = C.line;
    ctx.beginPath();
    ctx.moveTo(rx + 14, y + 92);
    ctx.lineTo(rx + cw - 14, y + 92);
    ctx.stroke();

    var lookbacks = [
      [t('month_ago'), disp('ratio.month_ago')],
      [t('quarter_ago'), opts.ratioQuarter || '–'],
      [t('half_year_ago'), opts.ratioHalfYear || '–'],
      [yearAgoLab, disp('ratio.year_ago')]
    ];
    lookbacks.forEach(function (kv, idx) {
      var ky = y + 114 + idx * 26;
      ctx.font = '400 11.5px ' + FONT_SANS;
      ctx.fillStyle = C.sub;
      ctx.fillText(kv[0], rx + 14, ky);
      ctx.textAlign = 'right';
      ctx.fillStyle = C.ink;
      ctx.fillText(kv[1], rx + cw - 14, ky);
      ctx.textAlign = 'left';
      if (idx < lookbacks.length - 1) {
        ctx.strokeStyle = C.lineSoft;
        ctx.beginPath();
        ctx.moveTo(rx + 14, ky + 8);
        ctx.lineTo(rx + cw - 14, ky + 8);
        ctx.stroke();
      }
    });
    y += ch + 14;

    // 3. 金银比百分位排名 + 历史走势图
    var heat = data.heatmap || {};
    var hw = (heat.windows && (heat.windows[winKey] || heat.windows['10y'])) || null;
    if (hw) {
      var hpH = 266;
      fillCard(ctx, PAD, y, IW, hpH);
      drawSectionTitle(ctx, t('heat_title') + ' · ' + t('heat_' + winKey), PAD + 16, y + 26);

      var pctVal = Number(hw.percentile || 0);
      ctx.font = '300 32px ' + FONT_SANS;
      ctx.fillStyle = C.gold;
      ctx.fillText(pctVal.toFixed(1) + '%', PAD + 16, y + 74);
      ctx.font = '400 11px ' + FONT_SANS;
      ctx.fillStyle = C.muted;
      ctx.fillText((lang === 'zh' ? '百分位排名 PR' : 'Percentile PR') + pctVal.toFixed(1), PAD + 16, y + 94);

      // 色带
      var bx = PAD + 170, bw = IW - 186, by = y + 58;
      var barGrad = ctx.createLinearGradient(bx, 0, bx + bw, 0);
      barGrad.addColorStop(0, '#2C6E9B');
      barGrad.addColorStop(0.25, '#3E9E8E');
      barGrad.addColorStop(0.5, '#C9A227');
      barGrad.addColorStop(0.75, '#D9722B');
      barGrad.addColorStop(1, '#C0392B');
      rr(ctx, bx, by, bw, 12, 6);
      ctx.fillStyle = barGrad;
      ctx.fill();

      var mx = bx + bw * Math.max(0, Math.min(100, pctVal)) / 100;
      ctx.fillStyle = '#FFFFFF';
      ctx.fillRect(mx - 1, by - 6, 2, 24);

      ctx.font = '400 10.5px ' + FONT_SANS;
      ctx.fillStyle = C.muted;
      ctx.fillText(
        t('heat_range', {
          min: Number(hw.min).toFixed(2),
          q1: Number(hw.p25 !== undefined ? hw.p25 : hw.q1).toFixed(2),
          med: Number(hw.median).toFixed(2),
          q3: Number(hw.p75 !== undefined ? hw.p75 : hw.q3).toFixed(2),
          max: Number(hw.max).toFixed(2)
        }),
        bx,
        by + 30
      );

      // 走势图
      var histPts = ((data.ratio_history && data.ratio_history.series) || [])
        .filter(function (p) { return p.date >= hw.start; })
        .map(function (p) { return { label: p.date, value: p.ratio }; });
      drawLineChart(ctx, PAD + 14, y + 114, IW - 28, 138, histPts, C.gold, heat.current);
      y += hpH + 14;
    }

    // 4. 印度与上海基准价表格
    var benchH = 186;
    fillCard(ctx, PAD, y, IW, benchH);
    drawSectionTitle(ctx, t('bench_title'), PAD + 16, y + 26);

    var vsLab = t(isReal ? 'vs_comex' : 'vs_tvc');
    ctx.font = '600 10px ' + FONT_SANS;
    ctx.fillStyle = C.faint;
    ctx.fillText(t('local_market'), PAD + 16, y + 50);
    ctx.textAlign = 'right';
    ctx.fillText(t('usd_per_oz'), PAD + IW - 160, y + 50);
    ctx.fillText(vsLab, PAD + IW - 16, y + 50);
    ctx.textAlign = 'left';

    var benchRows = [
      ['silver_india', 'bench.silver_india', 'bench.silver_india_premium'],
      ['silver_shanghai', 'bench.silver_shanghai', 'bench.silver_shanghai_premium'],
      ['gold_india', 'bench.gold_india', 'bench.gold_india_premium'],
      ['gold_shanghai', 'bench.gold_shanghai', 'bench.gold_shanghai_premium']
    ];
    benchRows.forEach(function (r, idx) {
      var ry = y + 76 + idx * 26;
      ctx.strokeStyle = C.lineSoft;
      ctx.beginPath();
      ctx.moveTo(PAD + 16, ry - 18);
      ctx.lineTo(PAD + IW - 16, ry - 18);
      ctx.stroke();

      ctx.font = '400 12px ' + FONT_SANS;
      ctx.fillStyle = C.sub;
      ctx.fillText(t(r[0]), PAD + 16, ry);
      ctx.textAlign = 'right';
      ctx.fillStyle = C.ink;
      ctx.fillText(disp(r[1]), PAD + IW - 160, ry);
      ctx.fillStyle = dirColor(field(r[2]));
      ctx.fillText(disp(r[2]), PAD + IW - 16, ry);
      ctx.textAlign = 'left';
    });
    y += benchH + 14;

    // 5. 实物白银库存 + COMEX 交割观察（两列并排）
    var g2w1 = Math.round((IW - gap) * 0.54);
    var g2w2 = IW - gap - g2w1;
    var g2h = 216;

    // 左：实物白银库存
    fillCard(ctx, PAD, y, g2w1, g2h);
    drawSectionTitle(ctx, t('vault_title') + ' (Moz)', PAD + 16, y + 26);
    ctx.font = '600 10px ' + FONT_SANS;
    ctx.fillStyle = C.faint;
    ctx.fillText(t('vault_col'), PAD + 16, y + 50);
    ctx.textAlign = 'right';
    ctx.fillText(t('latest'), PAD + g2w1 - 120, y + 50);
    ctx.fillText(t('change'), PAD + g2w1 - 62, y + 50);
    ctx.fillText(t('d30'), PAD + g2w1 - 14, y + 50);
    ctx.textAlign = 'left';

    var vRows = [
      ['vault_comex_reg', 'vault.comex_registered', 'vault.comex_registered_chg', 'vault.comex_registered_d30'],
      ['vault_comex_eligible', 'vault.comex_eligible', 'vault.comex_eligible_chg', 'vault.comex_eligible_d30'],
      ['vault_shfe', 'vault.shfe', 'vault.shfe_chg', null],
      ['vault_sge', 'vault.sge', null, null],
      ['vault_lbma', 'vault.lbma', null, 'vault.lbma_d30']
    ];
    vRows.forEach(function (r, idx) {
      var vy = y + 76 + idx * 27;
      ctx.strokeStyle = C.lineSoft;
      ctx.beginPath();
      ctx.moveTo(PAD + 16, vy - 18);
      ctx.lineTo(PAD + g2w1 - 14, vy - 18);
      ctx.stroke();

      ctx.font = '400 11.5px ' + FONT_SANS;
      ctx.fillStyle = C.sub;
      ctx.fillText(t(r[0]), PAD + 16, vy);
      ctx.textAlign = 'right';
      ctx.fillStyle = C.ink;
      ctx.fillText(disp(r[1]), PAD + g2w1 - 120, vy);
      ctx.fillStyle = r[2] ? dirColor(field(r[2])) : C.faint;
      ctx.fillText(r[2] ? disp(r[2]) : '–', PAD + g2w1 - 62, vy);
      ctx.fillStyle = r[3] ? dirColor(field(r[3])) : C.faint;
      ctx.fillText(r[3] ? disp(r[3]) : '–', PAD + g2w1 - 14, vy);
      ctx.textAlign = 'left';
    });

    // 右：COMEX 交割观察
    var cx2 = PAD + g2w1 + gap;
    fillCard(ctx, cx2, y, g2w2, g2h);
    drawSectionTitle(ctx, t('comex_title'), cx2 + 16, y + 26);

    ctx.font = '300 28px ' + FONT_SANS;
    ctx.fillStyle = C.gold;
    ctx.fillText(disp('comex.oi_to_registered'), cx2 + 16, y + 72);
    ctx.fillStyle = C.ink;
    ctx.fillText(disp('comex.registered_to_oi'), cx2 + g2w2 / 2 + 6, y + 72);

    ctx.font = '400 10px ' + FONT_SANS;
    ctx.fillStyle = C.faint;
    ctx.fillText(t('oi_to_reg'), cx2 + 16, y + 90);
    ctx.fillText(t('reg_to_oi'), cx2 + g2w2 / 2 + 6, y + 90);

    ctx.strokeStyle = C.line;
    ctx.beginPath();
    ctx.moveTo(cx2 + 16, y + 106);
    ctx.lineTo(cx2 + g2w2 - 16, y + 106);
    ctx.stroke();

    ctx.font = '600 12px ' + FONT_SANS;
    ctx.fillStyle = C.ink;
    ctx.fillText(disp('comex.notices_total'), cx2 + 16, y + 132);
    ctx.fillText(disp('comex.latest_report'), cx2 + g2w2 / 2 + 6, y + 132);

    ctx.font = '400 10px ' + FONT_SANS;
    ctx.fillStyle = C.faint;
    ctx.fillText(opts.noticesLabel || '', cx2 + 16, y + 148);
    ctx.fillText(t('latest_report'), cx2 + g2w2 / 2 + 6, y + 148);

    drawWrapped(
      ctx,
      String(disp('quality.stress_score')).replace(/<br\s*\/?>/g, ' '),
      cx2 + 16,
      y + 174,
      g2w2 - 32,
      15,
      C.faint,
      '400 10px ' + FONT_SANS
    );
    y += g2h + 14;

    // 6. 两条历史曲线并排（LBMA 库存 + CFTC 持仓）
    var curves = data.curves || {};
    if (curves.vault || curves.delivery) {
      var mcw = (IW - gap) / 2;
      var mch = 166;
      [
        ['vault', 'curve_vault_title', C.gold, PAD],
        ['delivery', 'curve_delivery_title', C.blue, PAD + mcw + gap]
      ].forEach(function (cfg) {
        var cv = curves[cfg[0]];
        if (!cv) return;
        fillCard(ctx, cfg[3], y, mcw, mch);
        drawSectionTitle(ctx, t(cfg[1]), cfg[3] + 14, y + 24);
        var st = cv.stats || {};
        ctx.font = '600 11px ' + FONT_SANS;
        ctx.fillStyle = C.sub;
        ctx.textAlign = 'right';
        ctx.fillText(Number(st.current || 0).toFixed(2) + ' ' + (cv.unit || ''), cfg[3] + mcw - 14, y + 24);
        ctx.textAlign = 'left';
        drawLineChart(ctx, cfg[3] + 10, y + 36, mcw - 20, 120, cv.points, cfg[2], st.current);
      });
      y += mch + 14;
    }

    // 7. 矿股 vs 金属
    var minH = 98;
    fillCard(ctx, PAD, y, IW, minH);
    drawSectionTitle(ctx, t('miners_title'), PAD + 16, y + 24);
    var halfW = IW / 2;
    [
      [0, 'gdx', 'miners.gdx', 'miners.gdx_day', 'miners.gold_day', 'miners.gdx_ratio_1y'],
      [1, 'sil', 'miners.sil', 'miners.sil_day', 'miners.silver_day', 'miners.sil_ratio_1y']
    ].forEach(function (m) {
      var mx = PAD + 16 + m[0] * halfW;
      if (m[0] === 1) {
        ctx.strokeStyle = C.line;
        ctx.beginPath();
        ctx.moveTo(PAD + halfW, y + 38);
        ctx.lineTo(PAD + halfW, y + minH - 14);
        ctx.stroke();
      }
      ctx.font = '400 11.5px ' + FONT_SANS;
      ctx.fillStyle = C.sub;
      ctx.fillText(t(m[1]), mx, y + 48);

      ctx.font = '600 16px ' + FONT_SANS;
      ctx.fillStyle = C.ink;
      var pText = disp(m[2]);
      ctx.fillText(pText, mx, y + 70);
      var pw = ctx.measureText(pText).width;

      ctx.font = '600 12px ' + FONT_SANS;
      ctx.fillStyle = dirColor(field(m[3]));
      var dText = disp(m[3]);
      ctx.fillText(dText, mx + pw + 8, y + 70);
      var dw = ctx.measureText(dText).width;

      ctx.font = '400 11px ' + FONT_SANS;
      ctx.fillStyle = C.muted;
      ctx.fillText(disp(m[4]), mx + pw + dw + 20, y + 70);

      ctx.font = '400 10.5px ' + FONT_SANS;
      ctx.fillStyle = C.faint;
      var rLab = t('etf_ratio') + ' ';
      ctx.fillText(rLab, mx, y + 88);
      ctx.fillStyle = dirColor(field(m[5]));
      ctx.fillText(disp(m[5]), mx + ctx.measureText(rLab).width, y + 88);
    });
    y += minH + 16;

    // 8. 页脚来源与免责声明
    ctx.strokeStyle = C.line;
    ctx.beginPath();
    ctx.moveTo(PAD, y);
    ctx.lineTo(W - PAD, y);
    ctx.stroke();
    y += 18;

    var srcText = t(isReal ? 'footer_sources_real' : 'footer_sources_text');
    y = drawWrapped(ctx, t('footer_sources') + '：' + srcText, PAD, y, IW, 15, C.faint, '400 10px ' + FONT_SANS);
    y += 4;
    y = drawWrapped(ctx, t('footer_disclaimer'), PAD, y, IW, 15, C.faint, '400 10px ' + FONT_SANS);
    y += 14;

    ctx.font = '600 11px ' + FONT_SANS;
    ctx.fillStyle = C.goldDim;
    ctx.fillText('METALS CLOSE  ·  ' + (data.report_date || ''), PAD, y);
    ctx.textAlign = 'right';
    ctx.fillStyle = C.faint;
    ctx.fillText('MetalCharts.org / Yahoo / SGE / SHFE / IBJA / CFTC / LBMA', W - PAD, y);
    ctx.textAlign = 'left';

    var finalH = Math.min(MAX_H, Math.ceil(y + 28));
    var out = document.createElement('canvas');
    out.width = W * DPR;
    out.height = finalH * DPR;
    var octx = out.getContext('2d');
    octx.drawImage(canvas, 0, 0, W * DPR, finalH * DPR, 0, 0, W * DPR, finalH * DPR);
    return {
      dataUrl: out.toDataURL('image/png'),
      width: W,
      height: finalH
    };
  }

  window.MCShare = { renderPoster: renderPoster };
})();
