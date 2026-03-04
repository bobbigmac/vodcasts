import { bootApp } from "./main/boot.js";

bootApp().catch((err) => {
  console.error(err);
});

