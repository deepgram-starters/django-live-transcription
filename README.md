# Django Live Transcription Starter

Get started using Deepgram's Live Transcription with this Django demo app. This application demonstrates real-time speech-to-text transcription using Deepgram's Speech to Text API.

## What is Deepgram?

[Deepgram’s](https://deepgram.com/) voice AI platform provides APIs for speech-to-text, text-to-speech, and full speech-to-speech voice agents. Over 200,000+ developers use Deepgram to build voice AI products and features.

## Sign-up to Deepgram

Before you start, it's essential to generate a Deepgram API key to use in this project. [Sign-up now for Deepgram and create an API key](https://console.deepgram.com/signup?jump=keys).

## Prerequisites

Before you start, ensure you have:
- Python 3.8+
- pip for package installation
- A [Deepgram API Key](https://console.deepgram.com/signup?jump=keys)

## Quickstart

Follow these steps to get started with this starter application.

### Clone the repository

1. Go to Github and [clone](https://github.com/deepgram-starters/flask-live-transcription.git)

2. Install dependencies

Install the project dependencies.

```bash
pip install -r requirements.txt
```
3. Set your Deepgram API key:

```bash
export DEEPGRAM_API_KEY=your_api_key_here
```

## Running the application

Start the application server:

```bash
python app.py
```

Then open your browser and go to:

```
http://localhost:8080

```
- Allow microphone access when prompted.
- Speak into your microphone to interact with the Deepgram Speech to Text API.
- You should see your audio transcription in your browser.

## Using Cursor & MDC Rules

This application can be modify as needed by using the [app-requirements.mdc](.cursor/rules/app-requirements.mdc) file. This file allows you to specify various settings and parameters for the application in a structured format that can be use along with [Cursor's](https://www.cursor.com/) AI Powered Code Editor.

### Using the `app-requirements.mdc` File

1. Clone or Fork this repo.
2. Modify the `app-requirements.mdc`
3. Add the necessary configuration settings in the file.
4. You can refer to the MDC file used to help build this starter application by reviewing  [app-requirements.mdc](.cursor/rules/app-requirements.mdc)

## Testing

Test the application with:

```bash
pytest -v test_app.py
```

## Getting Help

We love to hear from you so if you have questions, comments or find a bug in the project, let us know! You can either:

- [Open an issue in this repository](https://github.com/deepgram-starters/django-live-transcription/issues/new)
- [Join the Deepgram Github Discussions Community](https://github.com/orgs/deepgram/discussions)
- [Join the Deepgram Discord Community](https://discord.gg/deepgram)

## Contributing

See our [Contributing Guidelines](./CONTRIBUTING.md) to learn about contributing to this project.

## Code of Conduct

This project follows the [Deepgram Code of Conduct](./CODE_OF_CONDUCT.md).

## Security

For security policy and procedures, see our [Security Policy](./SECURITY.md).

## License

This project is licensed under the MIT license. See the [LICENSE](./LICENSE) file for more info.

## Author

[Deepgram](https://deepgram.com)

