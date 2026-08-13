import React, { useState } from "react";
import { StintEntry, TyreStrategyPredictionWire } from "../../types/raceMode";

interface TyreStintIndicatorProps {
  stints: StintEntry[];
  /** Gemini-predicted remaining strategy, race mode only - undefined until the driver's
   * first completed lap has produced one (see utils/tyre_strategy_prediction.py). */
  prediction?: TyreStrategyPredictionWire;
}

function compoundLetter(compound: string): string {
  return compound !== "unknown" ? compound[0].toUpperCase() : "?";
}

/** Race-mode-only tyre strategy popover, mirroring BattleRadarIndicator's hover pattern: the
 * row of small compound chips is the trigger, and hovering/focusing it reveals a horizontal
 * strategy bar - one segment per stint, width proportional to laps run on that set, so a
 * repeat stop onto the same compound (soft, hard, hard) reads as two distinct segments, not
 * one. Qualifying doesn't use this component at all (see TimingTower.tsx) - stint length in
 * laps isn't a meaningful concept for a handful of qualifying laps.
 *
 * When a prediction is available, a second "Predicted Strategy" bar renders below the actual
 * one - same visual language (segmented horizontal bar, one block per stint) but dashed/
 * lower-opacity so it always reads as a forecast, not fact, plus the model's one-line summary
 * and safety-car reasoning underneath. */
const TyreStintIndicator: React.FC<TyreStintIndicatorProps> = ({ stints, prediction }) => {
  const [open, setOpen] = useState(false);

  if (stints.length === 0) {
    return <span className="tyre-chip-mini unknown">?</span>;
  }

  return (
    <span
      className="tyre-stint-badge"
      tabIndex={0}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {stints.map((stint, i) => (
        <span
          key={i}
          className={`tyre-chip-mini ${stint.compound}${i === stints.length - 1 ? " current" : ""}`}
        >
          {compoundLetter(stint.compound)}
        </span>
      ))}
      {open && (
        <span className="tyre-stint-popover">
          <span className="tyre-stint-popover-head">Tyre Strategy</span>
          <span className="tyre-stint-popover-bar">
            {stints.map((stint, i) => (
              <span
                key={i}
                className={`tyre-stint-segment ${stint.compound}`}
                style={{ flexGrow: stint.laps && stint.laps > 0 ? stint.laps : 1 }}
              >
                <span className="tyre-stint-segment-compound">{compoundLetter(stint.compound)}</span>
                <span className="tyre-stint-segment-laps">
                  {stint.laps !== undefined ? `${stint.laps}L` : "?"}
                </span>
              </span>
            ))}
          </span>

          {prediction && (
            <>
              <span className="tyre-stint-popover-head predicted">
                Predicted Strategy <span className="tyre-stint-predicted-badge">Gemini</span>
              </span>
              <span className="tyre-stint-popover-bar predicted">
                {prediction.predicted_stints.map((stint) => (
                  <span
                    key={stint.stint_number}
                    className={`tyre-stint-segment predicted ${stint.compound}`}
                    style={{ flexGrow: stint.predicted_total_laps > 0 ? stint.predicted_total_laps : 1 }}
                  >
                    <span className="tyre-stint-segment-compound">{compoundLetter(stint.compound)}</span>
                    <span className="tyre-stint-segment-laps">{stint.predicted_total_laps}L</span>
                  </span>
                ))}
              </span>
              <span className="tyre-stint-predicted-summary">{prediction.summary}</span>
              <span className="tyre-stint-predicted-summary faint">{prediction.safety_car_note}</span>
              <span className="tyre-stint-predicted-footnote">as of lap {prediction.generated_at_lap}</span>
            </>
          )}
        </span>
      )}
    </span>
  );
};

export default TyreStintIndicator;
