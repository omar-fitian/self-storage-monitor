CHAIN_LABELS <- c(cubesmart = "CubeSmart", publicstorage = "Public Storage")

REMOTE_UNITS <- paste0("https://raw.githubusercontent.com/omar-fitian/",
                       "self-storage-monitor/refs/heads/main/dashboard/data/units.csv")

# The CSV on disk: what the scraper writes here while developing, and what
# rsconnect bundles at deploy time. Read directly on a laptop; on the server,
# only when GitHub cannot be reached.
LOCAL_UNITS <- "data/units.csv"

FETCH_INTERVAL_SECONDS <- 300

load_units <- function(path = REMOTE_UNITS) {
  # if (!file.exists(path)) {
  #   stop("No data at '", path, "'. Generate it with: python -m scraper", call. = FALSE)
  # }
  read_csv(path, show_col_types = FALSE) |>
    mutate(
      date = as.Date(date),
      chain = coalesce(unname(CHAIN_LABELS[source]), source),
      is_parking = grepl("parking|vehicle|rv|boat", category, ignore.case = TRUE),
      price_per_sqft = ifelse(is.na(area_sqft), NA_real_, price / area_sqft),
      discount_pct = ifelse(is.na(regular_price), NA_real_,
                            (1 - price / regular_price) * 100)
    )
}

# Carries the last fetch between sessions (multiple visitors share a process)
fetch_state <- new.env(parent = emptyenv())

# TRUE only when both signals agree this is a checkout. rsconnect deploys the
# dashboard directory alone, so a scraper beside it cannot exist on the server.
# Deployment is the assumption on anything ambiguous: mistaking the server for a
# laptop would pin the live dashboard to deploy-time prices, while the reverse
# only costs a fetch that was not needed.
running_locally <- function() {
  Sys.getenv("SHINY_PORT") == "" && dir.exists("../scraper")
}

# Returns units and source, so the UI can say so
# rather than quietly serving old prices as current ones.
units_snapshot <- function(force = FALSE) {
  # Developing: read what the scraper just wrote. No cache, so a re-scrape shows
  # on the next refresh instead of up to five minutes later.
  if (running_locally() && file.exists(LOCAL_UNITS)) {
    return(list(units = load_units(LOCAL_UNITS), stale = FALSE))
  }

  age <- if (is.null(fetch_state$fetched_at)) Inf else
    as.numeric(difftime(Sys.time(), fetch_state$fetched_at, units = "secs"))

  if (!force && age < FETCH_INTERVAL_SECONDS) return(fetch_state$snapshot)

  snapshot <- tryCatch(
    list(units = load_units(REMOTE_UNITS), stale = FALSE),
    error = function(e) {
      warning("Could not read ", REMOTE_UNITS, ": ", conditionMessage(e),
              " serving the last copy that loaded.", call. = FALSE)
      # Anything this process already fetched beats the bundle, which is only
      # as fresh as the last deploy. The bundle is for a cold start, when an
      # outage means there is no earlier fetch to fall back to.
      if (!is.null(fetch_state$snapshot)) {
        return(list(units = fetch_state$snapshot$units, stale = TRUE))
      }
      list(units = load_units(LOCAL_UNITS), stale = TRUE)
    }
  )
  # A failure is cached like a success, so an outage does not turn every
  # arriving visitor into another request against a service already failing.
  fetch_state$snapshot <- snapshot
  fetch_state$fetched_at <- Sys.time()
  snapshot
}
