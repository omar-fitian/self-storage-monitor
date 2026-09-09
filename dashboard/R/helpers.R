money <- function(x, digits = 2) {
  ifelse(is.na(x), "–", paste0("$", formatC(x, format = "f", digits = digits, big.mark = ",")))
}

# Footprints ordered by area, so filters and axes read small -> large.
footprint_levels <- function(units) {
  units |>
    distinct(unit_label, area_sqft) |>
    arrange(is.na(area_sqft), area_sqft, unit_label) |>
    pull(unit_label)
}
