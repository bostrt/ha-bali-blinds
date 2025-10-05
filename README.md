# Home Assistant Bali Blinds Integration

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

A custom Home Assistant integration for Bali Blinds devices.

## Installation

### HACS (Recommended)

1. Make sure you have [HACS](https://hacs.xyz/) installed
2. In the HACS panel, go to "Integrations"
3. Click the 3 dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL and select "Integration" as the category
6. Click "Install" on the Bali Blinds integration
7. Restart Home Assistant

### Manual Installation

1. Using the tool of choice, open the directory (folder) for your HA configuration (where you find `configuration.yaml`)
2. If you do not have a `custom_components` directory, create it
3. In the `custom_components` directory, create a new folder called `bali_blinds`
4. Download all the files from the `custom_components/bali_blinds/` directory in this repository
5. Place the files you downloaded in the new `bali_blinds` directory you created
6. Restart Home Assistant

## Configuration

1. In Home Assistant, go to Settings -> Devices & Services
2. Click "Add Integration"
3. Search for "Bali Blinds"
4. Follow the configuration steps

## Features

- **Cover entities** - Control your Bali Blinds (open, close, set position)
- **Sensor entities** - Monitor blind status and battery levels
- **Cloud polling** - Automatic status updates from the Bali Blinds cloud

## Development

### Prerequisites

- Python 3.13+
- Home Assistant development environment

### Testing

Run tests with pytest:

```bash
pytest tests/ \
  --cov=custom_components.bali_blinds \
  --cov-report term-missing
```

### Code Quality

This integration follows Home Assistant's code quality standards:

```bash
# Run all linters
pre-commit run --all-files

# Type checking
mypy custom_components/bali_blinds

# Linting
pylint custom_components/bali_blinds
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Thanks to the Home Assistant community for their support and guidance
- Inspired by other custom integrations like [ha-dyson](https://github.com/libdyson-wg/ha-dyson)

---

[releases-shield]: https://img.shields.io/github/release/bostrt/ha-bali-blinds.svg?style=for-the-badge
[releases]: https://github.com/bostrt/ha-bali-blinds/releases
[commits-shield]: https://img.shields.io/github/commit-activity/y/bostrt/ha-bali-blinds.svg?style=for-the-badge
[commits]: https://github.com/bostrt/ha-bali-blinds/commits/main
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/bostrt/ha-bali-blinds.svg?style=for-the-badge
