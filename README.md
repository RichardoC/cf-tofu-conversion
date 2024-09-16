# cf-tofu-conversion

For converting Cloudformation to opentofu/terraform

## Why?

cf2tf isn't able to convert everything directly, so why not have a language model do the drudgery of finishing the conversion

## How?

Run tofu/tf plan on the generated configuration, and if there's any drift, feed that to the model and the file to correct.

## Initial conversion

Use `cf2tf` [reference needed] which can be installed as folowing on macos

```console
brew install cf2tf
```

Example of using it on a CDK [reference needed] stack

```console
npx cdk synth  --all --outputs-file outputs.json --region eu-west-1  --profile PROFILE  -f
ls cdk.out/ | grep template | xargs -L1 -I{} cf2tf cdk.out/{} -o {}
```

When you check these generate tf files you'll see that there are various things this tool wasn't able to convert

## Tuning the configuration

```bash
python3 -m venv ./venv
source ./venv/bin/activate

AWS_PROFILE=some_profile python3 ./main.py --tf-bin "$(which tofu)" --input "/tf/tf.template.json" --output-folder "./tmp-output"
deactivate # disable the venv

```
