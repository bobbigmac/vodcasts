/**
 * Time-of-day helper for scene ambience.
 * Uses local time (user's timezone).
 * @returns {{ period: string, hour: number, blend: number, isDark: boolean }}
 */
export function getTimeOfDay() {
  const now = new Date();
  const hour = now.getHours() + now.getMinutes() / 60 + now.getSeconds() / 3600;

  let period, blend, isDark;
  if (hour >= 22 || hour < 5) {
    period = "night";
    blend = hour >= 22 ? (hour - 22) / 2 : (hour + 2) / 5;
    isDark = true;
  } else if (hour >= 5 && hour < 7) {
    period = "dawn";
    blend = (hour - 5) / 2;
    isDark = false;
  } else if (hour >= 7 && hour < 10) {
    period = "morning";
    blend = (hour - 7) / 3;
    isDark = false;
  } else if (hour >= 10 && hour < 14) {
    period = "day";
    blend = (hour - 10) / 4;
    isDark = false;
  } else if (hour >= 14 && hour < 17) {
    period = "afternoon";
    blend = (hour - 14) / 3;
    isDark = false;
  } else if (hour >= 17 && hour < 19) {
    period = "dusk";
    blend = (hour - 17) / 2;
    isDark = false;
  } else {
    period = "evening";
    blend = (hour - 19) / 3;
    isDark = true;
  }

  return { period, hour, blend, isDark };
}

/**
 * Get color palette for a scene based on time of day.
 * @returns {{ bg: string[], accent: string, muted: string }}
 */
export function getTimePalette() {
  const { period, blend } = getTimeOfDay();

  const palettes = {
    night: {
      bg: ["rgba(15, 20, 35, 0.85)", "rgba(25, 35, 55, 0.8)", "rgba(35, 45, 70, 0.75)"],
      accent: "rgba(160, 180, 220, 0.4)",
      muted: "rgba(120, 140, 180, 0.3)",
    },
    dawn: {
      bg: ["rgba(80, 60, 100, 0.6)", "rgba(60, 80, 120, 0.6)", "rgba(40, 55, 90, 0.7)"],
      accent: "rgba(200, 180, 220, 0.5)",
      muted: "rgba(160, 140, 200, 0.35)",
    },
    morning: {
      bg: ["rgba(100, 130, 170, 0.5)", "rgba(80, 110, 150, 0.55)", "rgba(60, 90, 130, 0.6)"],
      accent: "rgba(220, 235, 255, 0.6)",
      muted: "rgba(180, 200, 235, 0.4)",
    },
    day: {
      bg: ["rgba(140, 170, 210, 0.45)", "rgba(120, 150, 190, 0.5)", "rgba(100, 130, 170, 0.55)"],
      accent: "rgba(240, 248, 255, 0.7)",
      muted: "rgba(200, 220, 245, 0.5)",
    },
    afternoon: {
      bg: ["rgba(180, 160, 130, 0.5)", "rgba(160, 140, 110, 0.55)", "rgba(140, 120, 95, 0.6)"],
      accent: "rgba(255, 245, 220, 0.65)",
      muted: "rgba(220, 200, 170, 0.45)",
    },
    dusk: {
      bg: ["rgba(180, 100, 80, 0.55)", "rgba(120, 70, 90, 0.6)", "rgba(80, 50, 70, 0.65)"],
      accent: "rgba(255, 200, 160, 0.55)",
      muted: "rgba(220, 160, 140, 0.4)",
    },
    evening: {
      bg: ["rgba(50, 55, 90, 0.7)", "rgba(35, 45, 75, 0.75)", "rgba(25, 35, 60, 0.8)"],
      accent: "rgba(180, 200, 240, 0.45)",
      muted: "rgba(140, 160, 200, 0.35)",
    },
  };

  return palettes[period] || palettes.night;
}
