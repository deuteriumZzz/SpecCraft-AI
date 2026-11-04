// Источник стилей интерфейса. Сборка (из корня проекта):
//   npx tailwindcss@3.4.17 -c frontend/tailwind.config.js -i frontend/input.css \
//     -o app/static/tailwind.css --minify
// Готовый app/static/tailwind.css закоммичен: для запуска сервиса Node не нужен.
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

module.exports = {
  content: ["./app/static/index.html", "./app/static/app.js"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        paper: token("paper"),
        sheet: token("sheet"),
        ink: token("ink"),
        "ink-2": token("ink-2"),
        rule: token("rule"),
        accent: token("accent"),
        "accent-ink": token("accent-ink"),
        ok: token("ok"),
        gap: token("gap"),
        "gap-bg": token("gap-bg"),
        warn: token("warn"),
        "warn-bg": token("warn-bg"),
      },
      // Только системные шрифты: строгий CSP не разрешает внешние.
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SF Mono", "Menlo", "Consolas", "Liberation Mono", "monospace"],
      },
      // Токены движения. Длительности: instant 80 (нажатие), fast 180 (микро-отклик),
      // normal 350 (появление секций), slow 600 (данные на шкалах). Кривая одна на всё:
      // быстрый старт и мягкая остановка. Анимируются только transform и opacity.
      transitionDuration: { instant: "80ms", fast: "180ms", normal: "350ms", slow: "600ms" },
      transitionTimingFunction: { smooth: "cubic-bezier(0.22, 1, 0.36, 1)" },
      keyframes: {
        indeterminate: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(300%)" },
        },
        rise: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "none" },
        },
        fade: { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        indeterminate: "indeterminate 1.1s ease-in-out infinite",
        rise: "rise 350ms cubic-bezier(0.22, 1, 0.36, 1) both",
        // При «уменьшить движение» остаётся только затухание не дольше 0,2 с, без смещений.
        fade: "fade 180ms ease-out both",
      },
    },
  },
};
