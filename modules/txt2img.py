import json
from contextlib import closing

import modules.scripts
from modules import processing, infotext_utils
from modules.infotext_utils import create_override_settings_dict, parse_generation_parameters
from modules.shared import opts
import modules.shared as shared
from modules.ui import plaintext_to_html
from PIL import Image
import gradio as gr

# 定义一个函数，将文本转换为图像处理任务对象; 该函数接收一个任务ID、请求对象、文本提示、负面提示、提示样式、步数、采样器名称、迭代次数、批处理大小、配置比例、高度、宽度、是否启用高分辨率、去噪强度、高分辨率比例、高分辨率放大器、高分辨率第二次处理步数、高分辨率调整大小X、高分辨率调整大小Y、高分辨率检查点名称、高分辨率采样器名称、高分辨率提示、高分辨率负面提示、覆盖设置文本和其他参数
def txt2img_create_processing(id_task: str, request: gr.Request, prompt: str, negative_prompt: str, prompt_styles, steps: int, sampler_name: str, n_iter: int, batch_size: int, cfg_scale: float, height: int, width: int, enable_hr: bool, denoising_strength: float, hr_scale: float, hr_upscaler: str, hr_second_pass_steps: int, hr_resize_x: int, hr_resize_y: int, hr_checkpoint_name: str, hr_sampler_name: str, hr_prompt: str, hr_negative_prompt, override_settings_texts, *args, force_enable_hr=False):
    # 根据覆盖设置文本创建覆盖设置字典
    override_settings = create_override_settings_dict(override_settings_texts)

    # 如果强制启用高分辨率图像生成，则将 enable_hr 设置为 True
    if force_enable_hr:
        enable_hr = True

    # 创建 StableDiffusionProcessingTxt2Img 对象
    p = processing.StableDiffusionProcessingTxt2Img(
        sd_model=shared.sd_model,
        outpath_samples=opts.outdir_samples or opts.outdir_txt2img_samples,
        outpath_grids=opts.outdir_grids or opts.outdir_txt2img_grids,
        prompt=prompt,
        styles=prompt_styles,
        negative_prompt=negative_prompt,
        sampler_name=sampler_name,
        batch_size=batch_size,
        n_iter=n_iter,
        steps=steps,
        cfg_scale=cfg_scale,
        width=width,
        height=height,
        enable_hr=enable_hr,
        denoising_strength=denoising_strength,
        hr_scale=hr_scale,
        hr_upscaler=hr_upscaler,
        hr_second_pass_steps=hr_second_pass_steps,
        hr_resize_x=hr_resize_x,
        hr_resize_y=hr_resize_y,
        hr_checkpoint_name=None if hr_checkpoint_name == 'Use same checkpoint' else hr_checkpoint_name,
        hr_sampler_name=None if hr_sampler_name == 'Use same sampler' else hr_sampler_name,
        hr_prompt=hr_prompt,
        hr_negative_prompt=hr_negative_prompt,
        override_settings=override_settings,
    )

    # 设置脚本和脚本参数
    p.scripts = modules.scripts.scripts_txt2img
    p.script_args = args

    # 设置用户名称
    p.user = request.username

    # 如果启用控制台提示，则打印提示信息
    if shared.opts.enable_console_prompts:
        print(f"\ntxt2img: {prompt}", file=shared.progress_print_out)

    return p

# 定义一个函数，用于处理图像的高分辨率放大任务
def txt2img_upscale(id_task: str, request: gr.Request, gallery, gallery_index, generation_info, *args):
    # 断言确保图库中有图像需要放大
    assert len(gallery) > 0, 'No image to upscale'
    # 断言确保图像索引在合理范围内
    assert 0 <= gallery_index < len(gallery), f'Bad image index: {gallery_index}'

    # 创建图像处理任务对象，强制启用高分辨率图像生成
    p = txt2img_create_processing(id_task, request, *args, force_enable_hr=True)
    p.batch_size = 1
    p.n_iter = 1
    # 标记这是由 txt2img_upscale 调用的
    p.txt2img_upscale = True

    # 解析生成信息
    geninfo = json.loads(generation_info)

    # 获取图像信息
    image_info = gallery[gallery_index] if 0 <= gallery_index < len(gallery) else gallery[0]
    p.firstpass_image = infotext_utils.image_from_url_text(image_info)

    # 解析生成参数
    parameters = parse_generation_parameters(geninfo.get('infotexts')[gallery_index], [])
    p.seed = parameters.get('Seed', -1)
    p.subseed = parameters.get('Variation seed', -1)

    # 设置覆盖设置，不保存高分辨率图像
    p.override_settings['save_images_before_highres_fix'] = False

    # 执行图像处理任务
    with closing(p):
        processed = modules.scripts.scripts_txt2img.run(p, *p.script_args)

        # 如果处理结果为空，则进行图像处理
        if processed is None:
            processed = processing.process_images(p)

    shared.total_tqdm.clear()

    # 构建新的图库
    new_gallery = []
    for i, image in enumerate(gallery):
        if i == gallery_index:
            geninfo["infotexts"][gallery_index: gallery_index+1] = processed.infotexts
            new_gallery.extend(processed.images)
        else:
            fake_image = Image.new(mode="RGB", size=(1, 1))
            fake_image.already_saved_as = image["name"].rsplit('?', 1)[0]
            new_gallery.append(fake_image)

    geninfo["infotexts"][gallery_index] = processed.info

    return new_gallery, json.dumps(geninfo), plaintext_to_html(processed.info), plaintext_to_html(processed.comments, classname="comments")

# 定义一个函数，用于执行文本到图像生成任务
def txt2img(id_task: str, request: gr.Request, *args):
    # 创建图像处理任务对象
    p = txt2img_create_processing(id_task, request, *args)

    # 执行图像处理任务
    with closing(p):
        processed = modules.scripts.scripts_txt2img.run(p, *p.script_args)

        # 如果处理结果为空，则进行图像处理
        if processed is None:
            processed = processing.process_images(p)

    shared.total_tqdm.clear()

    # 将生成信息转换为 JavaScript 对象
    generation_info_js = processed.js()
    if opts.samples_log_stdout:
        print(generation_info_js)

    # 如果设置为不显示图像，则清空图像列表
    if opts.do_not_show_images:
        processed.images = []

    return processed.images, generation_info_js, plaintext_to_html(processed.info), plaintext_to_html(processed.comments, classname="comments")
