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
      keyframes: {
        indeterminate: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(300%)" },
        },
      },
      animation: { indeterminate: "indeterminate 1.1s ease-in-out infinite" },
    },
  },
};
