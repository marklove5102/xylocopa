import { useState, useEffect } from "react";
import { fluentFlatUrl } from "../lib/projectEmoji";

/**
 * Render an emoji using Microsoft Fluent UI Emoji (Flat) from jsdelivr CDN,
 * falling back to the system emoji font if the CDN asset isn't available.
 */
export default function FluentEmoji({ char, size = 18, className = "", title }) {
  const url = fluentFlatUrl(char);
  const [errored, setErrored] = useState(false);

  // Reset error flag when char changes so a new valid emoji gets another try.
  useEffect(() => { setErrored(false); }, [char]);

  if (!char) return null;

  if (!url || errored) {
    return (
      <span
        className={className}
        style={{ fontSize: size, lineHeight: 1, display: "inline-block" }}
        title={title || char}
      >
        {char}
      </span>
    );
  }

  return (
    <img
      src={url}
      alt={char}
      width={size}
      height={size}
      className={className}
      style={{ display: "inline-block" }}
      loading="lazy"
      draggable={false}
      onError={() => setErrored(true)}
      title={title || char}
    />
  );
}
