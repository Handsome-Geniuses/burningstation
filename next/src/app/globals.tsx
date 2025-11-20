"use client"; // important — this makes it a client component

import { useEffect } from "react";

export function Globals() {
  useEffect(() => {
    const preventContextMenu = (e: Event) => e.preventDefault();

    document.addEventListener("contextmenu", preventContextMenu);

    // clean up on unmount
    return () => {
      document.removeEventListener("contextmenu", preventContextMenu);
    };
  }, []);

  return null; // renders nothing
}
