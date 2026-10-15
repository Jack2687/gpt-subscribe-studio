import "@mantine/core/styles.css";
import "./styles.css";

import { MantineProvider } from "@mantine/core";
import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { theme } from "./theme";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <App />
    </MantineProvider>
  </React.StrictMode>,
);
