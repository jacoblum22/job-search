"""Browser pieces of the daily application goal, shared by the dashboard (the bar) and the
details page (the toast and confetti when "I applied" is pressed)."""

# Emoji stops along the bar, as a share of the goal: from crying at zero to star eyes at the goal.
STOPS = [(0, "😭"), (0.2, "😟"), (0.4, "😐"), (0.6, "🙂"), (0.8, "😄"), (1, "🤩")]

CSS = """
  .goalbar { flex: 1 1 260px; max-width: 380px; align-self: center; margin: 0 auto; }
  .goalbar[hidden] { display: none; }
  .goalbar .gtop { display: flex; justify-content: space-between; font-size: 13px; color: var(--muted); margin-bottom: 4px; }
  .goalbar .gtop b { color: var(--text); font-variant-numeric: tabular-nums; }
  .goalbar .gtrack { position: relative; height: 10px; background: #10131a; border-radius: 999px; margin: 0 10px; }
  .goalbar .gfill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #3a7d44, #6fcf7f); transition: width .5s ease; }
  .goalbar.done .gfill { background: linear-gradient(90deg, #c9a227, #f2d45c); }
  .goalbar .gstop { position: absolute; top: 50%; transform: translate(-50%, -50%); font-size: 15px; line-height: 1;
                    filter: grayscale(1); opacity: .45; transition: all .3s; }
  .goalbar .gstop.on { filter: none; opacity: 1; }
  .goal-toast { position: fixed; right: 20px; bottom: 20px; z-index: 1000; background: #1d3a24; color: #d6f2dc; border: 1px solid #3a7d44;
                border-radius: 10px; padding: 12px 16px; max-width: 320px; font-size: 14px; box-shadow: 0 8px 24px rgba(0,0,0,.4);
                transform: translateY(20px); opacity: 0; transition: all .3s; pointer-events: none; }
  .goal-toast.show { transform: none; opacity: 1; }
  .goal-toast b { display: block; font-size: 16px; margin-bottom: 2px; }
"""

JS = """
function goalBar(el, g) {
  if (!el || !g) return;
  const pct = Math.min(g.done / g.goal, 1);
  el.hidden = false;
  el.classList.toggle('done', g.done >= g.goal);
  el.querySelector('.gcount').textContent = `${g.done}/${g.goal}`;
  el.querySelector('.gfill').style.width = (pct * 100) + '%';
  el.querySelectorAll('.gstop').forEach(s => s.classList.toggle('on', pct >= parseFloat(s.dataset.at) && (pct > 0 || s.dataset.at === '0')));
}
function goalMessage(g) {
  const left = g.goal - g.done;
  if (g.done >= g.goal) return ['Goal hit! 🎉', `${g.done} applications today. Nice work.`];
  if (g.done === 1) return ['First one in!', `1 of ${g.goal} today. The hardest one is done.`];
  if (g.done / g.goal >= 0.8) return ['Almost there!', `${g.done} of ${g.goal}. Just ${left} more.`];
  if (g.done / g.goal >= 0.5) return ['Past halfway!', `${g.done} of ${g.goal} today. Keep going.`];
  return ['Application sent!', `${g.done} of ${g.goal} today.`];
}
function goalToast(g) {
  const [head, body] = goalMessage(g);
  const t = document.createElement('div');
  t.className = 'goal-toast';
  t.innerHTML = `<b></b><span></span>`;
  t.querySelector('b').textContent = head;
  t.querySelector('span').textContent = body;
  document.body.appendChild(t);
  requestAnimationFrame(() => t.classList.add('show'));
  setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 400); }, 4500);
}
function confetti() {
  const c = document.createElement('canvas');
  c.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:2000';
  c.width = innerWidth; c.height = innerHeight;
  document.body.appendChild(c);
  const ctx = c.getContext('2d'), colors = ['#6fcf7f', '#f2d45c', '#5b8cff', '#e57373', '#c58bff'];
  const bits = Array.from({length: 160}, () => ({
    x: Math.random() * c.width, y: -20 - Math.random() * c.height * 0.5, w: 6 + Math.random() * 6, h: 8 + Math.random() * 8,
    vx: -1.5 + Math.random() * 3, vy: 2 + Math.random() * 4, a: Math.random() * 6, va: -.2 + Math.random() * .4,
    color: colors[Math.floor(Math.random() * colors.length)]}));
  const end = performance.now() + 4000;
  (function frame(now) {
    ctx.clearRect(0, 0, c.width, c.height);
    for (const b of bits) {
      b.x += b.vx; b.y += b.vy; b.a += b.va;
      ctx.save(); ctx.translate(b.x, b.y); ctx.rotate(b.a); ctx.fillStyle = b.color;
      ctx.fillRect(-b.w / 2, -b.h / 2, b.w, b.h); ctx.restore();
    }
    if (now < end) requestAnimationFrame(frame); else c.remove();
  })(performance.now());
}
"""

BAR_HTML = (
    '<div class="goalbar" id="goalBar" hidden>'
    '<div class="gtop"><span>Applications today</span><b class="gcount">0/0</b></div>'
    '<div class="gtrack"><div class="gfill" style="width:0"></div>'
    + "".join(f'<span class="gstop" data-at="{at}" style="left:{at * 100}%">{emoji}</span>' for at, emoji in STOPS)
    + "</div></div>"
)
