/* Stockroom — small progressive enhancements */

(() => {
  /* Dismiss flash messages and clean the URL so a refresh doesn't repeat them. */
  document.querySelectorAll(".flash-close").forEach((button) => {
    button.addEventListener("click", () => {
      button.closest(".flash")?.remove();
      const url = new URL(window.location.href);
      url.searchParams.delete("msg");
      url.searchParams.delete("error");
      window.history.replaceState({}, "", url.toString());
    });
  });

  /* Dynamic item rows on the issue form. */
  const form = document.getElementById("issue-form");
  const rows = document.getElementById("issue-rows");

  if (form && rows) {
    const template = document.getElementById("issue-row-template");
    const addButton = document.getElementById("add-issue-row");
    const errorBox = document.getElementById("issue-form-error");

    const showError = (message) => {
      if (!errorBox) return;
      errorBox.textContent = message;
      errorBox.hidden = false;
    };

    const clearError = () => {
      if (!errorBox) return;
      errorBox.hidden = true;
      errorBox.textContent = "";
    };

    const pluralUnit = (count, unit) => {
      if (!unit || unit === "pcs") return unit;
      if (unit === "pair") return count === 1 ? "pair" : "pairs";
      return count === 1 ? unit : `${unit}s`;
    };

    const updateRow = (row) => {
      const select = row.querySelector('select[name="item_id"]');
      const hint = row.querySelector("[data-stock-hint]");
      const quantity = row.querySelector('input[name="quantity"]');
      if (!select || !hint) return;

      const option = select.selectedOptions[0];
      const rawStock = option?.dataset.stock;
      const unit = option?.dataset.unit || "";
      const extra = row.querySelector("[data-issue-extra]");
      const metresField = row.querySelector("[data-metres-field]");
      const serialsField = row.querySelector("[data-serials-field]");
      const metresInput = metresField?.querySelector("input");
      const serialsInput = serialsField?.querySelector("input");
      const showMetres =
        Number(option?.dataset.metresPerDrum || 0) > 0 || unit === "drum";
      const showSerials = option?.dataset.trackSerial === "1";

      hint.classList.remove("is-low", "is-ok");
      if (!select.value || rawStock === undefined) {
        hint.textContent = "Select an item to see availability";
        quantity?.removeAttribute("max");
        if (extra) extra.hidden = true;
        if (metresField) metresField.hidden = true;
        if (serialsField) serialsField.hidden = true;
        return;
      }

      const stock = Number(rawStock);
      hint.textContent = `Available: ${stock} ${pluralUnit(stock, unit)}`;
      hint.classList.add(stock > 0 ? "is-ok" : "is-low");
      if (stock > 0) {
        quantity?.setAttribute("max", String(stock));
      } else {
        quantity?.removeAttribute("max");
      }

      if (extra) {
        if (metresField) metresField.hidden = !showMetres;
        if (serialsField) serialsField.hidden = !showSerials;
        extra.hidden = !showMetres && !showSerials;
      }
      if (metresInput) {
        if (showMetres) {
          const perDrum = Number(option?.dataset.metresPerDrum || 0);
          metresInput.placeholder = perDrum > 0 ? `e.g. ${perDrum}` : "e.g. 2000";
        } else {
          metresInput.value = "";
        }
      }
      if (serialsInput && !showSerials) serialsInput.value = "";
    };

    const wireRow = (row) => {
      const select = row.querySelector('select[name="item_id"]');
      const quantity = row.querySelector('input[name="quantity"]');
      const remove = row.querySelector(".row-remove");

      select?.addEventListener("change", () => {
        clearError();
        updateRow(row);
      });
      quantity?.addEventListener("input", clearError);
      remove?.addEventListener("click", () => {
        const allRows = rows.querySelectorAll(".issue-row");
        if (allRows.length === 1) {
          if (select) select.value = "";
          if (quantity) quantity.value = "1";
          updateRow(row);
          clearError();
        } else {
          row.remove();
        }
      });

      updateRow(row);
    };

    rows.querySelectorAll(".issue-row").forEach(wireRow);

    addButton?.addEventListener("click", () => {
      if (!template) return;
      const row = template.content.firstElementChild.cloneNode(true);
      rows.appendChild(row);
      wireRow(row);
      row.querySelector("select")?.focus();
    });

    form.addEventListener("submit", (event) => {
      const keptRows = [];

      rows.querySelectorAll(".issue-row").forEach((row) => {
        const select = row.querySelector('select[name="item_id"]');
        if (!select || !select.value) {
          row.remove();
          return;
        }
        keptRows.push(row);
      });

      if (keptRows.length === 0) {
        event.preventDefault();
        showError("Choose at least one item for this issue.");
        return;
      }

      const seen = new Set();

      for (const row of keptRows) {
        const select = row.querySelector('select[name="item_id"]');
        const quantityInput = row.querySelector('input[name="quantity"]');
        const quantity = Number.parseInt(quantityInput?.value || "0", 10);
        const option = select.selectedOptions[0];
        const stock = Number(option?.dataset.stock || "0");
        const unit = option?.dataset.unit || "";
        const name = option?.textContent?.split(" — ")[0]?.trim() || "this item";

        if (!Number.isFinite(quantity) || quantity < 1) {
          event.preventDefault();
          showError("Enter a quantity greater than zero for every item.");
          quantityInput?.focus();
          return;
        }

        if (seen.has(select.value)) {
          event.preventDefault();
          showError(`${name} appears more than once. Combine it into one line.`);
          select.focus();
          return;
        }
        seen.add(select.value);

        if (quantity > stock) {
          event.preventDefault();
          showError(`Only ${stock} ${pluralUnit(stock, unit)} of ${name} are in stock.`);
          quantityInput?.focus();
          return;
        }
      }
    });
  }

  /* Show cable-metres and serial fields when the selected item needs them. */
  const stockItem = document.getElementById("item_id");
  const stockOptional = document.getElementById("stock-optional");
  if (stockItem && stockOptional) {
    const metresField = stockOptional.querySelector("[data-metres-field]");
    const serialsField = stockOptional.querySelector("[data-serials-field]");
    const metresInput = metresField?.querySelector("input");
    const serialsInput = serialsField?.querySelector("input");

    const updateStockOptional = () => {
      const option = stockItem.selectedOptions[0];
      const isCable =
        Number(option?.dataset.metresPerDrum || 0) > 0 ||
        option?.dataset.unit === "drum";
      const tracksSerial = option?.dataset.trackSerial === "1";

      if (metresField) metresField.hidden = !isCable;
      if (serialsField) serialsField.hidden = !tracksSerial;
      stockOptional.hidden = !isCable && !tracksSerial;

      if (!isCable && metresInput) metresInput.value = "";
      if (!tracksSerial && serialsInput) serialsInput.value = "";
      if (isCable && metresInput) {
        const perDrum = Number(option?.dataset.metresPerDrum || 0);
        metresInput.placeholder = perDrum > 0 ? `e.g. ${perDrum}` : "e.g. 2000";
      }
    };

    stockItem.addEventListener("change", updateStockOptional);
    updateStockOptional();
  }

  /* "All" shortcut on the record-return inputs. */
  document.querySelectorAll(".fill-return").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.target);
      if (!input) return;
      input.value = button.dataset.max || input.max;
      input.focus();
    });
  });

  /* Keep the active nav item visible in the horizontally scrolling mobile nav. */
  const activeNav = document.querySelector(".nav-link.is-active");
  if (activeNav && window.matchMedia("(max-width: 860px)").matches) {
    activeNav.scrollIntoView({ block: "nearest", inline: "center" });
  }
})();
