# Install the R packages the dashboard needs.
packages <- c(
  "shiny", "shinydashboard", "dplyr", "tidyr", "readr",
  "DT", "leaflet", "plotly"
)

missing <- setdiff(packages, rownames(installed.packages()))
if (length(missing)) {
  install.packages(missing, repos = "https://cloud.r-project.org")
} else {
  cat("All required packages are already installed.\n")
}
