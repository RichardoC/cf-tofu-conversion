#!/usr/bin/env python3

import argparse
import subprocess
import os
import sys
import time
from shutil import copytree
from openai import OpenAI

def parse_arguments():
    parser = argparse.ArgumentParser(description="Automate tofu planning and fixing using OpenAI GPT-4.")
    parser.add_argument('--tf-bin', required=True, help='Path to the tofu binary.')
    parser.add_argument('--input', required=True, help='Input folder for tofu.')
    parser.add_argument('--output-folder', required=True, help='Output folder for fixed files.')
    parser.add_argument('--original-template', required=True, help='Path to the original CloudFormation template.')
    parser.add_argument('--openai-api-key', default=None, help='OpenAI API key. Alternatively, set the OPENAI_API_KEY environment variable.')
    parser.add_argument('--openai-model', default='gpt-4o-mini-2024-07-18', help='OpenAI model name. Default is "gpt-4".')
    parser.add_argument('--max-retries', type=int, default=5, help='Maximum number of retries for fixing.')
    parser.add_argument('--sleep-interval', type=int, default=10, help='Seconds to wait between retries.')
    return parser.parse_args()

def initialize_openai(api_key):
    """
    Initializes the OpenAI API client with the provided API key.
    """
    if api_key:
        key = api_key
    else:
        key = os.getenv('OPENAI_API_KEY')
        if not key:
            print("Error: OpenAI API key not provided. Use the '--openai-api-key' argument or set the OPENAI_API_KEY environment variable.")
            sys.exit(1)
    client = OpenAI(
        api_key=key
    )
    return client

def run_tofu(tf_bin, working_folder):
    """
    Runs the tofu binary with 'plan -detailed-exitcode' arguments.
    Streams the output in real-time.
    Returns the exit code and accumulated output.
    """
    command = [tf_bin, 'plan', '-detailed-exitcode']
    try:
        process = subprocess.Popen(
            command,
            cwd=working_folder,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        accumulated_output = ""
        print("\n--- Tofu Output ---\n")
        
        # Stream stdout
        if process.stdout:
            for line in iter(process.stdout.readline, ''):
                print(line, end='')
                accumulated_output += line
        # Stream stderr
        if process.stderr:
            for line in iter(process.stderr.readline, ''):
                print(line, end='')
                accumulated_output += line

        process.stdout.close()
        process.stderr.close()
        return_code = process.wait()
        print(f"\nTofu exited with code {return_code}\n")
        return return_code, accumulated_output
    except Exception as e:
        print(f"Error running tofu: {e}")
        sys.exit(1)

def read_all_files(folder):
    """
    Reads all files in the specified folder and returns a dictionary of filename: content.
    Ignores the '.terraform' directory and its contents.
    """
    files_content = {}
    for root, dirs, files in os.walk(folder):
        # Ignore the '.terraform' directory
        if '.terraform' in dirs:
            dirs.remove('.terraform')
        for filename in files:
            filepath = os.path.join(root, filename)
            relative_path = os.path.relpath(filepath, folder)
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    files_content[relative_path] = file.read()
            except Exception as e:
                print(f"Error reading file {relative_path}: {e}")
                sys.exit(1)
    return files_content

def read_original_template(template_path):
    """
    Reads the original CloudFormation template file.
    Returns the filename and its content.
    """
    if not os.path.isfile(template_path):
        print(f"Original CloudFormation template not found at {template_path}")
        sys.exit(1)
    try:
        with open(template_path, 'r', encoding='utf-8') as file:
            content = file.read()
        filename = os.path.basename(template_path)
        return filename, content
    except Exception as e:
        print(f"Error reading original CloudFormation template: {e}")
        sys.exit(1)

def send_to_openai(client, model, messages):
    """
    Sends messages to the OpenAI API and streams the response in real-time.
    Returns the fixed files content as a dictionary.
    """
    try:
        print("\n--- Sending to OpenAI GPT-4 Model ---\n")
        fixed_files_text = ""
        
        # Initialize the streaming context
        with client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True
        ) as stream:
            print("\n--- OpenAI GPT-4 Model Response ---\n")
            for event in stream:
                
                # if 'choices' in event and len(event['choices']) > 0:
                content = event.choices[0].delta.content
                # content = delta.get('content', '')
                if content:
                    print(content, end='', flush=True)
                    fixed_files_text += content
                # else:
                #     print("failed to get response from OpenAI")
                #     print(event['choices'])

        print("\n")  # Ensure newline after streaming
        if not fixed_files_text.strip():
            print("Received empty response from OpenAI.")
            sys.exit(1)
        # Parse the fixed files from the response
        fixed_files = parse_fixed_files(fixed_files_text)
        return fixed_files
    except Exception as e:
        print(f"Error communicating with OpenAI: {e}")
        sys.exit(1)

def parse_fixed_files(fixed_files_text):
    """
    Parses the fixed files text returned from the model and returns a dictionary of filename: content.
    """
    fixed_files = {}
    lines = fixed_files_text.splitlines()
    current_file = None
    current_content = []
    for line in lines:
        if line.startswith("[START FILE: "):
            current_file = line[len("[START FILE: "):-1]  # Remove '[START FILE: ' and trailing ']'
            current_content = []
        elif line.strip() == "[END FILE]":
            if current_file:
                fixed_files[current_file] = "\n".join(current_content)
                current_file = None
        else:
            if current_file is not None:
                current_content.append(line)
    return fixed_files

def write_fixed_files(folder, fixed_files):
    """
    Writes the fixed files to the specified folder, preserving subdirectory structure.
    """
    for filename, content in fixed_files.items():
        output_path = os.path.join(folder, filename)
        output_dir = os.path.dirname(output_path)
        os.makedirs(output_dir, exist_ok=True)
        try:
            with open(output_path, 'w', encoding='utf-8') as file:
                file.write(content)
            print(f"Fixed {filename} written to {output_path}")
        except Exception as e:
            print(f"Error writing file {filename}: {e}")
            sys.exit(1)

def initialize_output_folder(input_folder, output_folder):
    """
    Copies all files from input_folder to output_folder if output_folder is empty.
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)
        print(f"Created output folder: {output_folder}")

    if not any(os.scandir(output_folder)):
        print("Output folder is empty. Copying files from input folder to output folder.")
        try:
            copytree(input_folder, output_folder, dirs_exist_ok=True)
            print("Files copied successfully.")
        except Exception as e:
            print(f"Error copying files to output folder: {e}")
            sys.exit(1)
    else:
        print(f"Output folder already contains files. Using existing files in {output_folder}.")

def main():
    args = parse_arguments()

    # Initialize OpenAI API client
    client = initialize_openai(args.openai_api_key)

    tf_bin = args.tf_bin
    input_folder = args.input
    output_folder = args.output_folder
    original_template_path = args.original_template
    openai_model = args.openai_model
    max_retries = args.max_retries
    sleep_interval = args.sleep_interval

    # Validate tofu binary
    if not os.path.isfile(tf_bin):
        print(f"Tofu binary not found at {tf_bin}")
        sys.exit(1)
    # Validate input folder
    if not os.path.isdir(input_folder):
        print(f"Input folder not found at {input_folder}")
        sys.exit(1)
    # Initialize output folder
    initialize_output_folder(input_folder, output_folder)
    # Read original CloudFormation template
    original_template = read_original_template(original_template_path)

    attempt = 0
    while attempt < max_retries:
        print(f"\nAttempt {attempt + 1} of {max_retries}: Running tofu...")
        exit_code, tofu_output = run_tofu(tf_bin, output_folder)

        if exit_code == 0:
            print("Tofu plan successful. No changes needed.")
            break
        else:
            print("Tofu plan failed. Attempting to fix files using OpenAI GPT-4 model.")
            files_content = read_all_files(output_folder)
            # Construct the prompt
            prompt = f"""The following is the output from the tofu tool:

{tofu_output}

Here are the contents of the files:

"""
            # Include all files from the output folder
            for filename, content in files_content.items():
                prompt += f"[START FILE: {filename}]\n{content}\n[END FILE]\n\n"

            # Include the original CloudFormation template
            original_filename, original_content = original_template
            prompt += f"[START FILE: {original_filename}]\n{original_content}\n[END FILE]\n\n"

            prompt += """Please fix the files based on the tofu output. Ensure that the Terraform configuration aligns with the provided CloudFormation template. Provide only the fixed file contents with no additional commentary, maintaining the same filenames and the same [START FILE] and [END FILE] markers for each file."""

            # Prepare the messages for the OpenAI chat
            messages = [
                {
                    'role': 'system',
                    'content': 'I am an expert at fixing Terraform files after a migration from CloudFormation. Please provide the output from the Terraform tool and the contents of the files that need to be fixed along with their original CloudFormation templates. I am extremely experienced with AWS.'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ]

            fixed_files = send_to_openai(client, openai_model, messages)
            write_fixed_files(output_folder, fixed_files)

            print("Re-running tofu with the fixed files.")

        attempt += 1
        if attempt < max_retries:
            print(f"Waiting for {sleep_interval} seconds before next attempt...\n")
            time.sleep(sleep_interval)
        else:
            print("Maximum number of retries reached. Exiting.")
            sys.exit(1)

if __name__ == "__main__":
    main()
