function make_video_grid_robust(in_dir, out_pdf, num_frames, frame_height)
%MAKE_VIDEO_GRID_ROBUST  PDF grid of sampled frames (.mp4) with FFmpeg fallback.
%   make_video_grid_robust('input', 'output/teaser.pdf', 4, 220)

    if nargin < 1, in_dir = 'input'; end
    if nargin < 2, out_pdf = 'output/teaser.pdf'; end
    if nargin < 3, num_frames = 4; end
    if nargin < 4, frame_height = 220; end
    assert(num_frames >= 1);

    vids = dir(fullfile(in_dir, '*.mp4'));
    if isempty(vids)
        error('No .mp4 videos found in "%s".', in_dir);
    end
    num_videos = numel(vids);

    % Layout
    aspect = 16/9; % just for tile size; actual frames are letterboxed
    frame_width = round(frame_height * aspect);
    fig_w = 40 + num_frames*frame_width + (num_frames-1)*6;
    fig_h = 40 + num_videos*frame_height + (num_videos-1)*6;

    fig = figure('Color','w','Position',[100 100 fig_w fig_h],'Visible','off');
    tl = tiledlayout(num_videos, num_frames, 'Padding','compact','TileSpacing','compact');

    for v = 1:num_videos
        vpath = fullfile(vids(v).folder, vids(v).name);
        vname = vids(v).name;

        % 1) Try VideoReader
        use_ffmpeg = false;
        try
            vr = VideoReader(vpath);
            T = vr.Duration;
            if ~isfinite(T) || T <= 0
                use_ffmpeg = true;
            end
        catch
            use_ffmpeg = true;
        end

        if ~use_ffmpeg
            % Sample with VideoReader
            ts = linspace(0.05*T, 0.95*T, num_frames);
            frames = cell(1, num_frames);
            for i = 1:num_frames
                try
                    vr.CurrentTime = ts(i);
                    img = readFrame(vr);
                catch
                    % In case readFrame fails midstream, retry via FFmpeg at this ts
                    img = grab_with_ffmpeg(vpath, ts(i));
                end
                frames{i} = resize_letterbox(img, [frame_height, frame_width]);
            end
        else
            % 2) FFmpeg fallback
            T = ffprobe_duration(vpath);
            if ~isfinite(T) || T <= 0
                warning('Cannot get duration for "%s". Using uniform frame index sampling.', vname);
                % Default to evenly spaced between 5% and 95% assuming ~10s
                T = 10;
            end
            ts = linspace(0.05*T, 0.95*T, num_frames);
            frames = cell(1, num_frames);
            for i = 1:num_frames
                img = grab_with_ffmpeg(vpath, ts(i));
                frames{i} = resize_letterbox(img, [frame_height, frame_width]);
            end
        end

        for f = 1:num_frames
            nexttile(tl, (v-1)*num_frames + f);
            imshow(frames{f}); axis image off
            if v == 1, title(sprintf('t%02d', f), 'FontSize', 9); end
            if f == 1, ylabel(ellipsize(vname, 40), 'FontSize', 9, 'Interpreter','none'); end
        end
    end

    % Save to PDF
    exportgraphics(fig, out_pdf, 'ContentType','vector');
    close(fig);
    fprintf('Saved PDF grid to: %s\n', out_pdf);
end

function img = grab_with_ffmpeg(vpath, t_sec)
% Extract a single frame at time t_sec using ffmpeg and read it back.
    tmp_png = [tempname, '.png'];
    % -y overwrite, -ss seek, -frames:v 1 take one frame, -loglevel error quiets output
    cmd = sprintf('ffmpeg -y -ss %.3f -i "%s" -frames:v 1 -loglevel error "%s"', ...
                  max(0, t_sec), vpath, tmp_png);
    st = system(cmd);
    if st ~= 0 || ~isfile(tmp_png)
        error('FFmpeg failed to extract frame at %.3fs from "%s".', t_sec, vpath);
    end
    img = imread(tmp_png);
    delete(tmp_png);
end

function dur = ffprobe_duration(vpath)
% Query duration (seconds) with ffprobe.
    cmd = sprintf('ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "%s"', vpath);
    [st, out] = system(cmd);
    if st == 0
        dur = str2double(strtrim(out));
    else
        dur = NaN;
    end
end

function out = resize_letterbox(im, out_size)
% Preserve aspect, pad to out_size with white background.
    target_h = out_size(1); target_w = out_size(2);
    im = ensure_rgb(im);
    [h, w, ~] = size(im);
    s = min(target_w / w, target_h / h);
    new_w = max(1, round(w * s));
    new_h = max(1, round(h * s));
    imr = imresize(im, [new_h, new_w], 'bilinear');

    out = uint8(255 * ones(target_h, target_w, 3));
    y0 = floor((target_h - new_h)/2) + 1;
    x0 = floor((target_w - new_w)/2) + 1;
    out(y0:y0+new_h-1, x0:x0+new_w-1, :) = imr;
end

function im = ensure_rgb(im)
    if ~isa(im,'uint8'), im = im2uint8(im); end
    if ndims(im) == 2, im = repmat(im, [1 1 3]); end
    if size(im,3) == 4
        rgb = im(:,:,1:3);
        a = double(im(:,:,4)) / 255;
        a = repmat(a, [1 1 3]);
        im = uint8(a .* double(rgb) + (1 - a) * 255);
    end
end

function s = ellipsize(name, maxlen)
    if numel(name) <= maxlen, s = name; return; end
    k = floor((maxlen - 3)/2);
    s = [name(1:k) '...' name(end-k+1:end)];
end

make_video_grid_robust('input', 'output/teaser.pdf', 4, 220);
